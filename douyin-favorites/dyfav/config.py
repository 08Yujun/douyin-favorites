"""配置加载：优先 config.toml，否则回退 config.example.toml。"""
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "better_favorites.db"
BROWSER_PROFILE = DATA_DIR / "browser_profile"
STATIC_DIR = Path(__file__).parent / "static"


def load_config() -> dict:
    for name in ("config.toml", "config.example.toml"):
        path = ROOT / name
        if path.exists():
            with open(path, "rb") as f:
                text = f.read().lstrip(b"\xef\xbb\xbf")  # 兼容个别工具写入的 BOM
            import tomllib as _t
            return _t.loads(text.decode("utf-8"))
    raise FileNotFoundError("找不到 config.toml / config.example.toml")


CONFIG = load_config()


def llm_config() -> dict:
    return CONFIG.get("llm", {})


def sync_config() -> dict:
    return CONFIG.get("sync", {})


def server_config() -> dict:
    return CONFIG.get("server", {})


def categories() -> list[dict]:
    return CONFIG.get("categories", [])


def category_names() -> list[str]:
    return [c["name"] for c in categories()]
