"""通过 Playwright 自动同步抖音「收藏」列表（v3 全自动）。

流程：打开浏览器 → 轮询检测登录（无需按任何键）→
自动进入个人主页点击「收藏」→ 自动滚动收集接口数据 → 写库并记录接口路径。
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from . import db
from .config import BROWSER_PROFILE, DATA_DIR, sync_config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def _walk(node, out: list) -> None:
    """递归查找所有含 aweme_id 的字典（宽容解析各种响应结构）。"""
    if isinstance(node, dict):
        if node.get("aweme_id"):
            out.append(node)
            return
        for v in node.values():
            _walk(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out)


def _normalize(d: dict, collected_at: str) -> dict | None:
    aid = str(d.get("aweme_id") or "")
    desc = (d.get("desc") or "").strip()
    if not aid or not desc:
        return None
    tags: list[str] = []
    for m in d.get("text_extra") or []:
        name = m.get("hashtag_name")
        if not name and isinstance(m.get("hashtag"), dict):
            name = m["hashtag"].get("hashtag_name")
        if name and name not in tags:
            tags.append(name)
    video = d.get("video") or {}
    cover = ""
    for key in ("cover", "origin_cover", "dynamic_cover"):
        obj = video.get(key)
        if isinstance(obj, dict) and obj.get("url_list"):
            cover = obj["url_list"][0]
            break
    published = ""
    create = d.get("create_time")
    if create:
        try:
            published = datetime.fromtimestamp(int(create)).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            pass
    return {
        "aweme_id": aid,
        "type": "image" if d.get("images") else "video",
        "title": desc,
        "desc": desc,
        "author": (d.get("author") or {}).get("nickname") or "",
        "author_id": str((d.get("author") or {}).get("uid") or ""),
        "tags": tags,
        "cover_url": cover,
        "share_url": video.get("share_url") or f"https://www.douyin.com/video/{aid}",
        "duration": int(video.get("duration") or 0),
        "published_at": published,
        "collected_at": collected_at,
        "raw": json.dumps(d, ensure_ascii=False)[:20000],
    }


def _harvest(found_items: list, seen: set[str]) -> tuple[int, int]:
    """返回 (本批采集条数, 其中数据库里原本没有的新条数)。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    scanned = 0
    fresh = 0
    for d in found_items:
        item = _normalize(d, now)
        if not item or item["aweme_id"] in seen:
            continue
        seen.add(item["aweme_id"])
        db.upsert_item(item)
        scanned += 1
        if not db.item_exists(item["aweme_id"]):
            fresh += 1
    return scanned, fresh


def _open_favorite_tab(page) -> bool:
    """进入个人主页并点击「收藏」标签。"""
    page.goto("https://www.douyin.com/user/self", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    for selector in ("text=收藏", "a:has-text('收藏')", "[role=tab]:has-text('收藏')"):
        try:
            page.locator(selector).first.click(timeout=2500)
            return True
        except Exception:
            continue
    return False


def _wait_login(ctx, page, timeout_s: int = 600) -> bool:
    """轮询 cookie 检测登录，成功返回 True。"""
    print("等待登录中：请在弹出的浏览器窗口里扫码（最长等 10 分钟）...")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            cookies = ctx.cookies()
            if any(c.get("name") == "sessionid" and c.get("value") for c in cookies):
                print("✓ 检测到登录成功")
                return True
        except Exception:
            pass
        page.wait_for_timeout(3000)
    print("等待登录超时")
    return False


def run_sync() -> None:
    cfg = sync_config()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright，请先执行：pip install playwright && playwright install chromium")
        return
    db.init_db()
    headless = bool(cfg.get("headless", False))
    max_items = int(cfg.get("max_items", 500))
    scroll_wait = int(float(cfg.get("scroll_wait", 1.5)) * 1000)
    log_path = DATA_DIR / "sync_urls.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    seen_paths: set[str] = set()
    seen: set[str] = set()
    captured: list = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(BROWSER_PROFILE), headless=headless, user_agent=UA,
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded")

        def on_response(r):
            u = r.url
            if not any(k in u for k in ("aweme", "collect", "favorite")):
                return
            try:
                u.split("?")[0]
                path = u.split("?")[0]
                seen_paths.add(path)
                _walk(r.json(), captured)
            except Exception:
                pass

        page.on("response", on_response)

        if not _wait_login(ctx, page):
            ctx.close()
            return

        opened = _open_favorite_tab(page)
        if not opened:
            print("⚠️ 自动打开「收藏」失败，尝试刷新后重试")
            page.wait_for_timeout(3000)
            opened = _open_favorite_tab(page)
        if not opened:
            print("⚠️ 仍失败：将在当前页面继续捕获（你也可以手动在浏览器里点开收藏页）")

        page.wait_for_timeout(3000)
        seen: set[str] = set()
        fresh_total = 0
        scanned_total = 0
        empty = 0
        threshold = int(cfg.get("empty_scrolls", 8))
        last_report = 0
        try:
            while fresh_total < max_items and empty < threshold:
                before = fresh_total
                n_scanned, fresh = _harvest(captured, seen)
                captured.clear()
                scanned_total += n_scanned
                fresh_total += fresh
                if fresh_total == before:
                    empty += 1
                else:
                    empty = 0
                if fresh_total - last_report >= 20:
                    print(f"  进度: 扫描 {scanned_total} 条，其中新收藏 {fresh_total} 条 ...")
                    last_report = fresh_total
                page.mouse.wheel(0, 3500)
                page.wait_for_timeout(scroll_wait)
        except Exception as exc:
            print(f"同步中断: {exc}")
        ctx.close()

    log_path.write_text("\n".join(sorted(seen_paths)) or "(空)", encoding="utf-8")
    print(f"接口路径 {len(seen_paths)} 个 → {log_path}")
    print(f"同步结束：扫描 {scanned_total} 条，本次新增 {fresh_total} 条 → {db.DB_PATH}")
