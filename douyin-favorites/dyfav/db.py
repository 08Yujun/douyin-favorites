"""SQLite 存储层：收藏条目 + 分类纠正样本。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    aweme_id     TEXT PRIMARY KEY,
    type         TEXT NOT NULL DEFAULT 'video',   -- video / image / playlist / other
    title        TEXT,
    desc         TEXT,
    author       TEXT,
    author_id    TEXT,
    tags         TEXT,        -- JSON 数组
    cover_url    TEXT,
    share_url    TEXT,
    duration     INTEGER,
    published_at TEXT,
    collected_at TEXT,        -- 收藏夹同步时间
    raw          TEXT,        -- 原始 JSON 片段，便于后续扩展
    summary      TEXT,        -- AI 要点
    labels       TEXT,        -- JSON 数组
    confidence   REAL,
    label_source TEXT,        -- llm / rule / manual
    enhanced_text TEXT,       -- 预留：转写/OCR 文本
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS corrections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    aweme_id   TEXT,
    text       TEXT,
    labels     TEXT,          -- JSON 数组
    created_at TEXT
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def upsert_item(item: dict) -> None:
    """新增或更新元数据；已生成的 summary/labels 不覆盖。"""
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO items (aweme_id, type, title, desc, author, author_id, tags,
                               cover_url, share_url, duration, published_at, collected_at, raw)
            VALUES (:aweme_id, :type, :title, :desc, :author, :author_id, :tags,
                    :cover_url, :share_url, :duration, :published_at, :collected_at, :raw)
            ON CONFLICT(aweme_id) DO UPDATE SET
                type = excluded.type,
                title = excluded.title,
                desc = excluded.desc,
                author = excluded.author,
                tags = excluded.tags,
                cover_url = COALESCE(NULLIF(excluded.cover_url, ''), items.cover_url),
                share_url = excluded.share_url,
                published_at = excluded.published_at,
                raw = excluded.raw
            """,
            {
                "aweme_id": item["aweme_id"],
                "type": item.get("type", "video"),
                "title": item.get("title") or "",
                "desc": item.get("desc") or "",
                "author": item.get("author") or "",
                "author_id": item.get("author_id") or "",
                "tags": json.dumps(item.get("tags", []), ensure_ascii=False),
                "cover_url": item.get("cover_url") or "",
                "share_url": item.get("share_url") or "",
                "duration": item.get("duration") or 0,
                "published_at": item.get("published_at") or "",
                "collected_at": item.get("collected_at") or _now(),
                "raw": item.get("raw") or "",
            },
        )


def reset_auto_labels() -> int:
    """清空自动生成的标签/摘要（人工改过的条目保留），返回受影响条数。"""
    with connect() as conn:
        cur = conn.execute(
            """UPDATE items SET labels=NULL, confidence=NULL, summary=NULL,
                               label_source=NULL
               WHERE label_source IS NULL OR label_source != 'manual'"""
        )
        return cur.rowcount


def reset_other_auto_labels() -> int:
    """只清空 LLM 打上「其他」的条目标签（用于类目扩展后的重分）。"""
    with connect() as conn:
        cur = conn.execute(
            """UPDATE items SET labels=NULL, confidence=NULL, summary=NULL,
                               label_source=NULL
               WHERE label_source='llm'
                 AND (labels LIKE '%"其他"%' OR labels = '[\"其他\"]')"""
        )
        return cur.rowcount


def item_exists(aweme_id: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM items WHERE aweme_id=?", (aweme_id,)).fetchone()
        return row is not None


def items_to_classify(limit: int | None = None) -> list[sqlite3.Row]:
    """取尚未分类的条目（人工改过的不再动）。"""
    sql = """
        SELECT * FROM items
        WHERE (summary IS NULL OR labels IS NULL OR labels = '[]')
          AND (label_source IS NULL OR label_source != 'manual')
        ORDER BY collected_at DESC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with connect() as conn:
        return conn.execute(sql).fetchall()


def set_classification(aweme_id: str, labels: list[str], confidence: float,
                       summary: str, source: str) -> None:
    with connect() as conn:
        conn.execute(
            """UPDATE items SET labels=?, confidence=?, summary=?, label_source=?, updated_at=?
               WHERE aweme_id=?""",
            (json.dumps(labels, ensure_ascii=False), confidence, summary, source, _now(), aweme_id),
        )


def manual_labels(aweme_id: str, labels: list[str]) -> bool:
    """人工改分类：更新条目并写入纠正样本，供 LLM few-shot 学习。"""
    with connect() as conn:
        row = conn.execute("SELECT title, desc, author, tags FROM items WHERE aweme_id=?",
                           (aweme_id,)).fetchone()
        if not row:
            return False
        conn.execute(
            """UPDATE items SET labels=?, confidence=1.0, label_source='manual', updated_at=?
               WHERE aweme_id=?""",
            (json.dumps(labels, ensure_ascii=False), _now(), aweme_id),
        )
        text = " ".join(x for x in (row["title"], row["desc"], row["author"],
                                    (row["tags"] or "").strip('[]"\\"')) if x)
        conn.execute(
            "INSERT INTO corrections (aweme_id, text, labels, created_at) VALUES (?,?,?,?)",
            (aweme_id, text[:500], json.dumps(labels, ensure_ascii=False), _now()),
        )
    return True


def few_shot_samples(n: int = 8) -> list[tuple[str, list[str]]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT text, labels FROM corrections ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [(r["text"], json.loads(r["labels"])) for r in rows]


def list_items(category: str | None = None, label: str | None = None, q: str | None = None,
               limit: int = 120, offset: int = 0) -> list[dict]:
    where, params = [], []
    if category and category != "全部":
        where.append("type = ?")
        params.append(category)
    if label == "未分类":
        where.append("(labels IS NULL OR labels = '[]')")
    elif label and label != "全部":
        where.append("labels LIKE ?")
        params.append(f'%"{label}"%')
    if q:
        where.append("(title LIKE ? OR desc LIKE ? OR summary LIKE ? OR tags LIKE ?)")
        params.extend([f"%{q}%"] * 4)
    sql = "SELECT * FROM items"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY collected_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d["tags"] or "[]")
        d["labels"] = json.loads(d["labels"] or "[]")
        out.append(d)
    return out


def stats() -> dict:
    out: dict = {"total": 0, "types": {}, "labels": [], "unclassified": 0}
    with connect() as conn:
        out["total"] = conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
        for r in conn.execute("SELECT type t, COUNT(*) c FROM items GROUP BY type"):
            out["types"][r["t"]] = r["c"]
        out["unclassified"] = conn.execute(
            "SELECT COUNT(*) c FROM items WHERE labels IS NULL OR labels = '[]'"
        ).fetchone()["c"]
        rows = conn.execute(
            "SELECT labels FROM items WHERE labels IS NOT NULL AND labels != '[]'"
        ).fetchall()
    counter: dict[str, int] = {}
    for r in rows:
        for name in json.loads(r["labels"]):
            counter[name] = counter.get(name, 0) + 1
    out["labels"] = sorted(
        ({"name": k, "count": v} for k, v in counter.items()), key=lambda x: -x["count"]
    )
    return out
