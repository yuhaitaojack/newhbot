from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PositionSide, SystemState
from app.events.hub import EventHub
from app.execution.protocol import ExecutionClient
from app.models import StrategyParameter, StrategyVersion
from app.recovery.manager import RecoveryManager
from app.repositories import (
    AuditRepository,
    EventRepository,
    OrderRepository,
    SettingsRepository,
    StrategyRepository,
)
from app.strategy.store import content_hash, manifest_to_json, write_version_dir
from app.strategy.validate import (
    MAX_MANIFEST_BYTES,
    MAX_STRATEGY_BYTES,
    StrategyValidationError,
    assert_expected_filename,
    validate_manifest,
    validate_strategy_source,
)
from app.strategy.yaml_lite import YamlLiteError, parse_yaml_lite


class StrategyService:
    def __init__(
        self,
        *,
        versions_root: Path,
        execution: ExecutionClient,
        hub: EventHub,
        recovery: RecoveryManager,
    ) -> None:
        self._root = versions_root
        self._execution = execution
        self._hub = hub
        self._recovery = recovery

    async def upload(
        self,
        session: AsyncSession,
        *,
        field_names: set[str],
        strategy_name: str | None,
        manifest_name: str | None,
        strategy_py: bytes,
        manifest_yaml: bytes,
    ) -> dict:
        try:
            self._validate_files(field_names, strategy_name, manifest_name, strategy_py, manifest_yaml)
            parsed = parse_yaml_lite(manifest_yaml.decode("utf-8"))
            manifest = validate_manifest(parsed)
            validate_strategy_source(strategy_py.decode("utf-8"))
        except (StrategyValidationError, YamlLiteError, UnicodeDecodeError) as exc:
            await AuditRepository(session).add(
                "strategy_upload_rejected", json.dumps({"reason": str(exc)}), actor="user"
            )
            await session.commit()
            return {"ok": False, "reason": str(exc)}

        file_hash = content_hash(strategy_py, manifest_yaml)
        repo = StrategyRepository(session)
        existing = await repo.get_by_hash(file_hash)
        if existing is not None:
            await AuditRepository(session).add(
                "strategy_upload",
                json.dumps({"file_hash": file_hash, "duplicate": True}),
                actor="user",
            )
            await session.commit()
            return {
                "ok": True,
                "duplicate": True,
                "file_hash": existing.file_hash,
                "name": existing.name,
                "version": existing.version,
                "path": existing.path,
                "activated": False,
            }

        dest = write_version_dir(self._root, file_hash, strategy_py, manifest_yaml)
        rel = dest.as_posix()
        row = StrategyVersion(
            name=manifest["name"],
            version=manifest["version"],
            file_hash=file_hash,
            path=rel,
            manifest_json=manifest_to_json(manifest["raw"] if isinstance(manifest["raw"], dict) else manifest),
        )
        await repo.add_version(row)
        raw = manifest["raw"] if isinstance(manifest["raw"], dict) else {}
        for item in raw.get("parameters") or []:
            if not isinstance(item, dict) or "name" not in item:
                continue
            default = item.get("default", "")
            await repo.add_parameter(
                StrategyParameter(
                    strategy_version_id=row.id,
                    name=str(item["name"]),
                    type=str(item.get("type") or "string"),
                    default_value=str(default),
                    current_value=str(default),
                    enabled=False,
                    min_value=None if item.get("min") is None else str(item.get("min")),
                    max_value=None if item.get("max") is None else str(item.get("max")),
                    description=None if item.get("description") is None else str(item.get("description")),
                )
            )
        await AuditRepository(session).add(
            "strategy_upload",
            json.dumps({"file_hash": file_hash, "name": row.name, "version": row.version}),
            actor="user",
        )
        event = await EventRepository(session).add(
            "strategy_upload",
            json.dumps({"file_hash": file_hash, "name": row.name, "version": row.version, "activated": False}),
        )
        await session.commit()
        await self._hub.publish("strategy_upload", {"file_hash": file_hash}, event.id)
        return {
            "ok": True,
            "duplicate": False,
            "file_hash": file_hash,
            "name": row.name,
            "version": row.version,
            "path": row.path,
            "activated": False,
        }

    async def activate(self, session: AsyncSession, file_hash: str) -> dict:
        settings = await SettingsRepository(session).get()
        repo = StrategyRepository(session)
        version = await repo.get_by_hash(file_hash)
        if version is None:
            return await self._activate_reject(session, "strategy version is not registered")

        if await OrderRepository(session).has_unresolved():
            return await self._activate_reject(session, "unresolved or UNKNOWN orders present")
        if settings.system_state != SystemState.STOPPED.value:
            return await self._activate_reject(
                session, f"cannot activate while {settings.system_state}"
            )

        try:
            position = await self._execution.get_position(settings.trading_pair)
        except Exception as exc:
            await self._recovery.enter_recovery(
                session, f"strategy_activate_position_query_failed:{type(exc).__name__}"
            )
            return await self._activate_reject(session, f"position query failed: {type(exc).__name__}")
        if position.side == PositionSide.UNKNOWN:
            await self._recovery.enter_recovery(session, "strategy_activate_position_unknown")
            return await self._activate_reject(session, "cannot activate while position is UNKNOWN")
        if position.side != PositionSide.FLAT:
            return await self._activate_reject(session, "cannot activate while a position is open")

        try:
            positions = await self._execution.get_positions()
            open_orders = await self._execution.get_open_orders()
        except Exception as exc:
            await self._recovery.enter_recovery(
                session, f"strategy_activate_exchange_query_failed:{type(exc).__name__}"
            )
            return await self._activate_reject(session, f"exchange query failed: {type(exc).__name__}")
        if any(item.side == PositionSide.UNKNOWN for item in positions):
            await self._recovery.enter_recovery(session, "strategy_activate_position_unknown")
            return await self._activate_reject(session, "cannot activate while position is UNKNOWN")
        if any(item.side != PositionSide.FLAT for item in positions):
            await self._recovery.enter_recovery(session, "strategy_activate_foreign_position")
            return await self._activate_reject(session, "cannot activate while an exchange position is open")
        if open_orders:
            await self._recovery.enter_recovery(session, "strategy_activate_open_orders")
            return await self._activate_reject(session, "cannot activate while exchange open orders are present")

        settings.active_strategy = version.name
        settings.active_strategy_version = version.version
        settings.trading_enabled = False
        if settings.system_state != SystemState.STOPPED.value:
            settings.system_state = SystemState.STOPPED.value
        await AuditRepository(session).add(
            "strategy_activate",
            json.dumps({"file_hash": file_hash, "name": version.name, "version": version.version}),
            actor="user",
        )
        event = await EventRepository(session).add(
            "strategy_status",
            json.dumps(
                {
                    "active_strategy": version.name,
                    "active_strategy_version": version.version,
                    "trading_enabled": False,
                }
            ),
        )
        await session.commit()
        await self._hub.publish(
            "strategy_status",
            {
                "active_strategy": version.name,
                "active_strategy_version": version.version,
                "trading_enabled": False,
            },
            event.id,
        )
        return {
            "ok": True,
            "name": version.name,
            "version": version.version,
            "file_hash": file_hash,
            "state": SystemState.STOPPED.value,
            "trading_enabled": False,
        }

    async def _activate_reject(self, session: AsyncSession, reason: str) -> dict:
        await AuditRepository(session).add(
            "strategy_activate_rejected", json.dumps({"reason": reason}), actor="user"
        )
        await session.commit()
        return {"ok": False, "reason": reason}

    def _validate_files(
        self,
        field_names: set[str],
        strategy_name: str | None,
        manifest_name: str | None,
        strategy_py: bytes,
        manifest_yaml: bytes,
    ) -> None:
        allowed = {"strategy.py", "manifest.yaml"}
        extra = field_names - allowed
        missing = allowed - field_names
        if extra:
            raise StrategyValidationError("only strategy.py and manifest.yaml are allowed")
        if missing:
            raise StrategyValidationError("strategy.py and manifest.yaml are required")
        assert_expected_filename(strategy_name, "strategy.py")
        assert_expected_filename(manifest_name, "manifest.yaml")
        if len(strategy_py) > MAX_STRATEGY_BYTES or len(manifest_yaml) > MAX_MANIFEST_BYTES:
            raise StrategyValidationError("file too large")
        if not strategy_py.strip() or not manifest_yaml.strip():
            raise StrategyValidationError("uploaded files must not be empty")
