from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def _sqlite_source_path(database_url: str) -> Path | None:
    if "sqlite" not in database_url or ":///" not in database_url:
        return None
    raw_path = database_url.split(":///", 1)[1]
    if raw_path in {":memory:", ""}:
        return None
    return Path(raw_path).resolve()


def backup_sqlite_file(database_url: str, destination: str | None = None) -> Path | None:
    """Create an atomic SQLite backup, including WAL state, via sqlite backup API."""
    source = _sqlite_source_path(database_url)
    if source is None or not source.is_file():
        return None
    target = (
        Path(destination).expanduser().resolve()
        if destination
        else source.parent / "backups" / source.name
    )
    if target == source:
        raise ValueError("SQLite backup destination must differ from the database")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        if temporary.exists():
            temporary.unlink()
        source_conn = sqlite3.connect(source)
        target_conn = sqlite3.connect(temporary)
        try:
            source_conn.backup(target_conn)
            target_conn.execute("PRAGMA synchronous=FULL")
            target_conn.commit()
        finally:
            target_conn.close()
            source_conn.close()
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


class DatabaseBackupService:
    def __init__(self, database_url: str, destination: str | None, interval_seconds: float) -> None:
        self._database_url = database_url
        self._destination = destination
        self._interval_seconds = max(float(interval_seconds), 1.0)
        self._task: asyncio.Task | None = None

    async def backup_once(self) -> Path | None:
        return await asyncio.to_thread(
            backup_sqlite_file, self._database_url, self._destination
        )

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="database-backup")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval_seconds)
                await self.backup_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("SQLite backup failed")
