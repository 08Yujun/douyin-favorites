"""定时自动同步 + 分类循环（常驻）。

以 [auto].interval_minutes 为周期执行一轮：
  无头浏览器抓取最新收藏（利用已保存登录态）→ LLM 增量分类新条目。
检查/重启方式：查看 data/auto.log；电脑重启后由开机自启快捷方式拉起。
"""
from __future__ import annotations

import time
import traceback
from datetime import datetime
from pathlib import Path

from .config import CONFIG, DATA_DIR

LOG = DATA_DIR / "auto.log"


def _log(msg: str) -> None:
    line = f"{datetime.now():%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_forever() -> None:
    minutes = float(CONFIG.get("auto", {}).get("interval_minutes", 180))
    interval = minutes * 60
    _log(f"自动同步循环启动，每 {minutes:g} 分钟执行一轮")
    while True:
        try:
            from . import classify, sync
            _log("开始同步收藏...")
            sync.run_sync()
            _log("开始增量分类...")
            classify.run(reset=False)
            _log("本轮完成")
        except Exception as exc:  # noqa: BLE001
            _log(f"本轮出错: {exc}")
            _log(traceback.format_exc()[-1200:])
        # 睡眠也记日志，方便判断程序是否还活着
        _log(f"进入休眠，{minutes:g} 分钟后开始下一轮")
        time.sleep(interval)
