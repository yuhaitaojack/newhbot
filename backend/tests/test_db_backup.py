from __future__ import annotations

import asyncio
import sqlite3

from app.db_backup import DatabaseBackupService, backup_sqlite_file


def test_sqlite_backup_uses_online_backup_and_is_readable(tmp_path) -> None:
    source = tmp_path / "newhbot.db"
    destination = tmp_path / "backups" / "newhbot.db"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE audit (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO audit(value) VALUES ('safe')")
        connection.commit()

    result = backup_sqlite_file(f"sqlite+aiosqlite:///{source.as_posix()}", str(destination))

    assert result == destination.resolve()
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM audit").fetchone() == ("safe",)


def test_backup_service_can_start_and_stop(tmp_path) -> None:
    source = tmp_path / "newhbot.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE audit (id INTEGER PRIMARY KEY)")
        connection.commit()

    service = DatabaseBackupService(
        f"sqlite+aiosqlite:///{source.as_posix()}", None, 300
    )
    async def exercise() -> None:
        await service.start()
        await service.stop()

    asyncio.run(exercise())


def test_backup_service_refreshes_backup_on_interval(tmp_path) -> None:
    source = tmp_path / "newhbot.db"
    destination = tmp_path / "backups" / "newhbot.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE audit (id INTEGER PRIMARY KEY, value TEXT)")
        connection.commit()

    service = DatabaseBackupService(
        f"sqlite+aiosqlite:///{source.as_posix()}", str(destination), 1
    )

    async def exercise() -> None:
        await service.start()
        with sqlite3.connect(source) as connection:
            connection.execute("INSERT INTO audit(value) VALUES ('periodic')")
            connection.commit()
        await asyncio.sleep(1.2)
        await service.stop()

    asyncio.run(exercise())

    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM audit").fetchone() == ("periodic",)
