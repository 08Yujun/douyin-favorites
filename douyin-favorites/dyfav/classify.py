"""分类：关键词规则前置 + LLM 批量多标签分类（任意 OpenAI 兼容接口）。"""
from __future__ import annotations

import json
import re
import time

import httpx

from . import db
from .config import categories, category_names, llm_config

BATCH_SIZE = 8


def _text_of(row) -> str:
    tags = row["tags"]
    if isinstance(tags, str):
        try:
            tags = json.loads(tags or "[]")
        except json.JSONDecodeError:
            tags = []
    if not isinstance(tags, list):
        tags = []
    parts = [
        row["title"] or "",
        row["desc"] or "",
        row["author"] or "",
        " ".join(str(t) for t in tags),
        (row["enhanced_text"] or "")[:400],
    ]
    return " ".join(p for p in parts if p)


def rule_match(text: str) -> list[str]:
    """关键词命中直接归类（跳过「其他」兜底类，由 LLM 决定）。"""
    low = text.lower()
    hits: list[str] = []
    for cat in categories():
        if cat.get("name") == "其他":
            continue
        for kw in cat.get("keywords", []):
            if kw and kw.lower() in low:
                hits.append(cat["name"])
                break
    return hits


SYSTEM = (
    "你是个人收藏整理助手。阅读类目清单和出发点，为【每一条】内容分别输出分类与要点。"
    '必须输出一个 JSON 数组（不要输出其他文字），每个元素形如：'
    '{"id":编号,"labels":["类目名"],"confidence":0至1的小数,"summary":"不超过40字的要点"}。'
    "labels 最多 2 个且必须来自类目清单；没有把握就返回空数组。"
    "summary 是对该条内容的一句话概括，不是复述标题。"
    "条目必须与输入一一对应、不合并不遗漏。"
)


def _extract_json(content: str) -> object | None:
    for pattern in (r"\[.*\]", r"\{.*\}", r"```json\s*(.*?)\s*```"):
        m = re.search(pattern, content, re.S)
        if not m:
            continue
        try:
            return json.loads(m.group(0) if pattern.endswith("`") else m.group(0))
        except json.JSONDecodeError:
            continue
    return None


def _llm_request(messages: list[dict]) -> str | None:
    cfg = llm_config()
    key = str(cfg.get("api_key", ""))
    base = str(cfg.get("base_url", "")).rstrip("/")
    for attempt in range(3):
        try:
            resp = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": cfg.get("model", ""),
                      "messages": messages, "temperature": 0.1, "max_tokens": 6000,
                      "thinking": {"type": "disabled"}},
                timeout=90,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(6 * (attempt + 1))  # 限流/瞬时错误，退避重试
                continue
            print(f"  LLM 请求失败: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001
            if attempt < 2:
                time.sleep(6)
                continue
            print(f"  LLM 请求失败: {exc}")
            return None
    return None


def call_llm_batch(numbered_items: list[tuple[int, str]]) -> dict[int, dict]:
    """一次请求对多条内容分类；返回 {编号: {"labels","confidence","summary"}}。"""
    cats = "；".join(f"{c['name']}：{c.get('description', '')}" for c in categories())
    entries = "\n\n".join(
        f"### 第{n}条\n{text}" for n, text in numbered_items
    )
    messages: list[dict] = [{"role": "system", "content": SYSTEM},
                            {"role": "user",
                             "content": f"类目清单：{cats}\n\n待分类条目：\n{entries}"}]
    content = _llm_request(messages)
    if not content:
        content = _llm_request(messages)  # 失败重试一次
        if not content:
            return {}
    data = _extract_json(content)
    if not data:
        return {}
    items = data if isinstance(data, list) else data.get("items", [])
    out: dict[int, dict] = {}
    valid = set(category_names())
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            idx = int(str(it.get("id", "0")))
        except (TypeError, ValueError):
            continue
        labels = []
        for x in it.get("labels", [])[:3]:
            if x in valid and x not in labels:
                labels.append(x)
        try:
            conf = float(it.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.5
        out[idx] = {"labels": labels, "confidence": conf,
                    "summary": str(it.get("summary", ""))[:80]}
    return out


def _classify_all_with_llm(rows) -> None:
    cfg = llm_config()
    done = 0
    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start:start + BATCH_SIZE]
        numbered = [(i + 1, _text_of(r)[:500]) for i, r in enumerate(chunk)]
        results = call_llm_batch(numbered)
        for i, row in enumerate(chunk, 1):
            res = results.get(i)
            if res:
                labels = res["labels"] or ["其他"]
                db.set_classification(row["aweme_id"], labels,
                                      res["confidence"], res["summary"], "llm")
            else:
                db.set_classification(row["aweme_id"], [], 0.0,
                                      (row["title"] or "")[:40], "none")
        done += len(chunk)
        print(f"  [{done}/{len(rows)}] 已处理")
        time.sleep(1.0)


def _classify_rules_only(rows) -> None:
    for i, row in enumerate(rows, 1):
        text = _text_of(row)
        labels = rule_match(text)
        if labels:
            db.set_classification(row["aweme_id"], labels, 0.9,
                                  (row["title"] or "")[:40], "rule")
        else:
            db.set_classification(row["aweme_id"], [], 0.0,
                                  (row["title"] or "")[:40], "none")
        print(f"[{i}/{len(rows)}] {(row['title'] or '')[:24]}… → "
              f"{'、'.join(labels) if labels else '未识别'}")


def run(limit: int | None = None, reset: bool | str = False) -> None:
    cfg = llm_config()
    key = str(cfg.get("api_key", ""))
    has_llm = bool(key and not key.startswith("sk-xxxx") and len(key) > 20)
    if has_llm and (reset is True or reset == "full"):
        n = db.reset_auto_labels()
        print(f"已重置全部 {n} 条自动标签，交由 LLM 重新分类")
    elif reset == "other":
        n = db.reset_other_auto_labels()
        print(f"已清空 {n} 条「其他」标签，交由 LLM 按新类目重新细分")
    elif not has_llm and not reset:
        print("未配置 LLM（config.toml 中 [llm].api_key），仅按关键词规则增量分类")
    else:
        print("LLM 增量分类（保留已有标签）")

    rows = db.items_to_classify(limit)
    print(f"待分类 {len(rows)} 条")
    if not rows:
        return
    if has_llm:
        _classify_all_with_llm(rows)
    else:
        _classify_rules_only(rows)
    print("分类完成")
