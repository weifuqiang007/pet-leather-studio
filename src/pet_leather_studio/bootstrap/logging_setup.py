"""最小日志（PRD M0 交付项，11.3 规范）。

日志写入 DATA_ROOT/runtime/logs/，轮转；格式含 UTC 时间、level、component。
不默认记录照片内容等隐私数据。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)sZ %(levelname)s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def setup_logging(level: int = logging.INFO) -> Path:
    """初始化根日志器，返回日志文件路径。重复调用幂等。"""
    from pet_leather_studio.bootstrap import environment

    log_dir = environment.data_root() / "runtime" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"

    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return log_path

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    formatter.converter = __import__("time").gmtime  # type: ignore[attr-defined]

    file_handler = RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    root.setLevel(level)
    return log_path
