"""抖音收藏盒 - 命令行入口

用法:
  python main.py init-db    初始化数据库
  python main.py demo       写入演示数据（无账号也可预览界面）
  python main.py sync       打开浏览器同步抖音收藏
  python main.py classify   对未分类内容执行规则+LLM分类
  python main.py web        启动本地界面 http://127.0.0.1:8642
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dyfav import db  # noqa: E402

DEMO_ITEMS = [
    ("video", "示例：AI Agent 入门，工作流编排一讲到底", "示例作者", "2026-10-14 17:51", ["AI学习"], "manual"),
    ("video", "示例：这个开源项目让你白嫖大模型 token", "示例作者", "2026-10-14 14:10", ["AI学习"], "rule"),
    ("video", "示例：GitHub 爆星 4.6 万的开源项目推荐", "示例作者", "2026-10-13 22:44", ["AI学习"], "rule"),
    ("video", "示例：智能体工作流 #工作流 #ai #人工智能", "示例作者", "2026-10-13 22:41", [], None),
    ("video", "示例：考研政治马原考点串讲", "示例作者", "2026-10-10 21:07", ["高考学习"], "rule"),
    ("video", "示例：AI时代会越来越值钱的能力", "示例作者", "2026-10-10 19:32", [], None),
    ("video", "示例：程序员如何少走弯路", "示例作者", "2026-10-10 17:22", [], None),
    ("video", "示例：高数定积分经典例题精讲", "示例作者", "2026-10-10 13:18", [], None),
    ("video", "示例：为什么总理解不到对方的意思？", "示例作者", "2026-10-10 13:11", [], None),
    ("image", "示例：男生化妆新手教程三步走 #妆教", "示例作者", "2026-10-09 20:05", ["化妆变帅"], "manual"),
]


def cmd_demo() -> None:
    db.init_db()
    base = datetime.now()
    for i, (typ, title, author, collected, labels, source) in enumerate(DEMO_ITEMS):
        days_ago = base - timedelta(days=i + 1)
        item = {
            "aweme_id": f"demo_{i:03d}",
            "type": typ,
            "title": title,
            "desc": title,
            "author": author,
            "author_id": "",
            "tags": [],
            "cover_url": "",
            "share_url": "https://www.douyin.com/discover",
            "duration": 0,
            "published_at": "",
            "collected_at": collected,
            "raw": "",
        }
        db.upsert_item(item)
        if labels:
            db.set_classification(item["aweme_id"], labels, 0.99, title[:40], source)
    print(f"已写入 {len(DEMO_ITEMS)} 条演示数据，运行 python main.py web 预览界面")


def cmd_sync() -> None:
    from dyfav import sync  # 延迟导入，避免未装 playwright 报错
    sync.run_sync()


def cmd_classify(limit: int | None, reset: str | None) -> None:
    from dyfav import classify
    classify.run(reset=reset or False, limit=limit)


def cmd_auto() -> None:
    from dyfav.auto import run_forever
    run_forever()


def cmd_web() -> None:
    import uvicorn
    from dyfav.config import server_config
    cfg = server_config()
    print(f"界面地址: http://{cfg.get('host', '127.0.0.1')}:{cfg.get('port', 8642)}")
    uvicorn.run("dyfav.server:app", host=cfg.get("host", "127.0.0.1"),
                port=int(cfg.get("port", 8642)), log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser(description="抖音收藏盒：同步/分类/浏览")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="初始化数据库")
    sub.add_parser("demo", help="写入演示数据")
    sub.add_parser("sync", help="同步抖音收藏")
    p_classify = sub.add_parser("classify", help="分类未归类条目")
    p_classify.add_argument("limit", nargs="?", type=int, default=None,
                            help="最多处理条数")
    p_classify.add_argument("-r", "--reset", choices=["full", "other"],
                            default=None,
                            help="full=全部重分；other=只重分「其他」类；缺省=增量")
    sub.add_parser("web", help="启动本地界面")
    sub.add_parser("auto", help="常驻：定时自动同步+分类")
    args = parser.parse_args()

    if args.cmd == "init-db":
        db.init_db()
        print(f"数据库已初始化: {db.DB_PATH}")
    elif args.cmd == "demo":
        cmd_demo()
    elif args.cmd == "sync":
        cmd_sync()
    elif args.cmd == "classify":
        cmd_classify(args.limit, args.reset)
    elif args.cmd == "web":
        cmd_web()
    elif args.cmd == "auto":
        cmd_auto()


if __name__ == "__main__":
    main()
