from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from app.controllers.position_guard import GuardInput, PositionGuard
from app.core.enums import PositionSide, SignalType, SystemState
from app.repositories import StrategyParameter, effective_parameter_value

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_alembic_upgrade_creates_tables(tmp_path, monkeypatch) -> None:
    db_file = tmp_path / "phase2.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.chdir(BACKEND_ROOT)
    from alembic import command
    from sqlalchemy import create_engine, inspect

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")
    inspector = inspect(create_engine(f"sqlite:///{db_file.as_posix()}"))
    tables = set(inspector.get_table_names())
    for name in (
        "settings",
        "strategy_versions",
        "strategy_parameters",
        "signals",
        "orders",
        "fills",
        "trades",
        "positions",
        "account_snapshots",
        "system_events",
        "audit_logs",
        "open_reservations",
    ):
        assert name in tables
    indexes = {item["name"] for item in inspector.get_indexes("orders")}
    assert "ix_orders_cloid" in indexes
    assert "uq_orders_intent_id" in indexes
    assert "uq_orders_request_id" in indexes
    assert "uq_orders_inflight_open_per_symbol" in indexes
    fill_indexes = {item["name"] for item in inspector.get_indexes("fills")}
    assert "uq_fills_exchange_fill_id" in fill_indexes or any(
        "exchange_fill_id" in (item.get("name") or "") for item in inspector.get_indexes("fills")
    )


def test_effective_parameter_uses_default_when_disabled() -> None:
    param = StrategyParameter(
        strategy_version_id=1,
        name="lookback",
        type="int",
        default_value="20",
        current_value="99",
        enabled=False,
    )
    assert effective_parameter_value(param) == "20"
    param.enabled = True
    assert effective_parameter_value(param) == "99"


def test_guard_allows_flat_flat_running() -> None:
    guard = PositionGuard()
    result = guard.can_open_position(
        GuardInput(
            local_side=PositionSide.FLAT,
            exchange_side=PositionSide.FLAT,
            has_unknown_orders=False,
            system_state=SystemState.RUNNING,
            configured_pair="BTC-USD",
            target_pair="BTC-USD",
            exchange_connected=True,
        )
    )
    assert result.allowed is True


def test_guard_rejects_long_plus_long() -> None:
    guard = PositionGuard()
    result = guard.can_open_position(
        GuardInput(
            local_side=PositionSide.LONG,
            exchange_side=PositionSide.LONG,
            has_unknown_orders=False,
            system_state=SystemState.RUNNING,
            configured_pair="BTC-USD",
            target_pair="BTC-USD",
            exchange_connected=True,
        )
    )
    assert result.allowed is False


def test_guard_rejects_long_plus_short() -> None:
    guard = PositionGuard()
    result = guard.can_open_position(
        GuardInput(
            local_side=PositionSide.LONG,
            exchange_side=PositionSide.SHORT,
            has_unknown_orders=False,
            system_state=SystemState.RUNNING,
            configured_pair="BTC-USD",
            target_pair="BTC-USD",
            exchange_connected=True,
        )
    )
    assert result.allowed is False
    assert guard.reverse_is_forbidden(PositionSide.LONG, SignalType.SHORT) is True
    assert guard.reverse_is_forbidden(PositionSide.SHORT, SignalType.LONG) is True


def test_guard_rejects_unknown_and_recovery() -> None:
    guard = PositionGuard()
    unknown = guard.can_open_position(
        GuardInput(
            local_side=PositionSide.FLAT,
            exchange_side=PositionSide.FLAT,
            has_unknown_orders=True,
            system_state=SystemState.RUNNING,
            configured_pair="BTC-USD",
            target_pair="BTC-USD",
            exchange_connected=True,
        )
    )
    recovery = guard.can_open_position(
        GuardInput(
            local_side=PositionSide.FLAT,
            exchange_side=PositionSide.FLAT,
            has_unknown_orders=False,
            system_state=SystemState.RECOVERY,
            configured_pair="BTC-USD",
            target_pair="BTC-USD",
            exchange_connected=True,
        )
    )
    assert unknown.allowed is False
    assert recovery.allowed is False


def test_guard_rejects_exchange_not_flat() -> None:
    guard = PositionGuard()
    result = guard.can_open_position(
        GuardInput(
            local_side=PositionSide.FLAT,
            exchange_side=PositionSide.LONG,
            has_unknown_orders=False,
            system_state=SystemState.RUNNING,
            configured_pair="BTC-USD",
            target_pair="BTC-USD",
            exchange_connected=True,
        )
    )
    assert result.allowed is False


def test_decimal_size_placeholder() -> None:
    from decimal import Decimal

    assert Decimal("10") > 0
