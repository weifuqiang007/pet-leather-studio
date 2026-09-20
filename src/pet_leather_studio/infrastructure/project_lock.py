"""Operating-system advisory lock released even if a worker is killed."""

from __future__ import annotations

import os
from pathlib import Path


class ProjectLock:
    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def acquire(self):
        if self.stream is not None:
            raise ValueError("当前工程已有写任务")
        stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if self.path.stat().st_size == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise ValueError("工程正在被另一个任务写入，请稍后重试") from exc
        self.stream = stream

    def release(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
