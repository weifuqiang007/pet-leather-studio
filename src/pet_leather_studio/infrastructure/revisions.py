"""SQLite revision index with staged immutable files; activation never rewrites geometry."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pet_leather_studio.infrastructure.project_lock import ProjectLock


class RevisionStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("revisions", "staging"):
            (self.root / name).mkdir(exist_ok=True)
        self.lock = ProjectLock(self.root / "write.lock")
        self.db = self.root / "project.sqlite"
        with self.connect() as con:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("不支持该工程数据版本，禁止降级写入")
            con.execute("CREATE TABLE IF NOT EXISTS revisions (id TEXT PRIMARY KEY, data TEXT)")
            con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            con.execute("PRAGMA user_version=1")

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db, timeout=10)

    def directory(self, revision_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", revision_id):
            raise ValueError("无效版本 ID")
        return self.root / "revisions" / revision_id

    def begin(self) -> Path:
        self.lock.acquire()
        try:
            path = self.root / "staging" / uuid.uuid4().hex
            path.mkdir()
            return path
        except BaseException:
            self.lock.release()
            raise

    def discard(self, stage: Path) -> None:
        if stage.parent.resolve() != (self.root / "staging").resolve():
            raise ValueError("拒绝清理工程 staging 之外的目录")
        shutil.rmtree(stage, ignore_errors=True)
        self.lock.release()

    def publish(self, stage: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        revision_id = stage.name
        target = self.directory(revision_id)
        metadata = dict(metadata, id=revision_id, created_at=datetime.now(UTC).isoformat())
        metadata["files"] = {
            f.name: {"sha256": file_hash(f), "bytes": f.stat().st_size}
            for f in sorted(stage.iterdir())
            if f.is_file()
        }
        data = json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False)
        (stage / "manifest.json").write_text(data, encoding="utf-8")
        stage.rename(target)
        # A crash before commit may leave an orphan, never a false success or lost version.
        with self.connect() as con:
            con.execute("INSERT INTO revisions VALUES (?, ?)", (revision_id, data))
            con.execute("INSERT OR REPLACE INTO settings VALUES ('active', ?)", (revision_id,))
        self.lock.release()
        return metadata

    def get(self, revision_id: str | None = None) -> dict[str, Any]:
        with self.connect() as con:
            if revision_id is None:
                row = con.execute("SELECT value FROM settings WHERE key='active'").fetchone()
                if row is None:
                    raise ValueError("请先导入浮雕母版")
                revision_id = row[0]
            self.directory(revision_id)
            row = con.execute("SELECT data FROM revisions WHERE id=?", (revision_id,)).fetchone()
        if row is None:
            raise ValueError("版本不存在")
        return dict(json.loads(row[0]))

    def history(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            return [
                json.loads(row[0])
                for row in con.execute("SELECT data FROM revisions ORDER BY rowid DESC")
            ]

    def verify(self, revision_id: str) -> None:
        metadata = self.get(revision_id)
        for name, expected in metadata["files"].items():
            if Path(name).name != name:
                raise ValueError("版本文件名不能包含路径")
            if file_hash(self.directory(revision_id) / name) != expected["sha256"]:
                raise ValueError(f"版本文件已变化，拒绝使用：{name}")

    def prune_staging(self, min_age_hours: float = 1.0) -> list[str]:
        """显式清理崩溃残留的 staging 目录。

        仅在成功取得写锁（无其他任务运行）时执行，只动 staging，
        不触碰 revisions 历史与用户数据；返回被清理的目录名。
        """
        self.lock.acquire()
        try:
            cutoff = time.time() - min_age_hours * 3600
            removed: list[str] = []
            for entry in (self.root / "staging").iterdir():
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed.append(entry.name)
            return removed
        finally:
            self.lock.release()

    def activate(self, revision_id: str) -> None:
        self.lock.acquire()
        try:
            self.verify(revision_id)
            with self.connect() as con:
                con.execute("INSERT OR REPLACE INTO settings VALUES ('active', ?)", (revision_id,))
        finally:
            self.lock.release()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
