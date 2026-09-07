"""Existing GET /api/status mirror path. Uses FakeExecutionClient, not live Hyperliquid."""

from __future__ import annotations

from decimal import Decimal

from app.core.enums import PositionSide
from app.execution.protocol import OrderView, PositionView
from app.core.enums import OrderSide, OrderStatus, OrderType


def test_status_upserts_single_exchange_mirror_row(app_client) -> None:
    client, _, fake = app_client
    fake.positions["BTC-USD"] = PositionView(
        symbol="BTC-USD",
        side=PositionSide.LONG,
        size=Decimal("0.01"),
        entry_price=Decimal("65000"),
        unrealized_pnl=Decimal("1"),
    )
    first = client.get("/api/status")
    assert first.status_code == 200
    pos = first.json()["position"]
    assert pos["side"] == PositionSide.LONG.value
    assert pos["source"] == "exchange_mirror"
    assert pos["size"] == "0.01"
    second = client.get("/api/status")
    assert second.json()["position"]["side"] == PositionSide.LONG.value
    listed = client.get("/api/positions")
    assert len(listed.json()) == 1
    assert listed.json()[0]["source"] == "exchange_mirror"


def test_status_query_failure_does_not_overwrite_existing_mirror(app_client) -> None:
    client, _, fake = app_client
    fake.positions["BTC-USD"] = PositionView(
        symbol="BTC-USD",
        side=PositionSide.SHORT,
        size=Decimal("0.02"),
        entry_price=Decimal("64000"),
        unrealized_pnl=Decimal("0"),
    )
    seeded = client.get("/api/status")
    assert seeded.json()["position"]["side"] == PositionSide.SHORT.value
    fake.get_position_error = True
    failed = client.get("/api/status")
    assert failed.status_code == 200
    assert failed.json()["position"]["side"] == PositionSide.SHORT.value
    assert failed.json()["position"]["source"] == "exchange_mirror"


def test_status_query_failure_stops_running_loop_and_enters_recovery(app_client) -> None:
    client, _, fake = app_client
    assert client.post("/api/trading/start").json()["ok"] is True
    fake.get_position_error = True

    failed = client.get("/api/status")
    assert failed.status_code == 200
    assert failed.json()["system_state"] == "RECOVERY"
    assert failed.json()["strategy_loop_running"] is False


def test_worker_status_failure_returns_safe_recovery_status(app_client) -> None:
    client, _, fake = app_client
    assert client.post("/api/trading/start").json()["ok"] is True
    fake.worker_status_error = True

    failed = client.get("/api/status")

    assert failed.status_code == 200
    body = failed.json()
    assert body["system_state"] == "RECOVERY"
    assert body["worker_ready"] is False
    assert body["worker_state"] == "UNKNOWN"
    assert body["sync_status"] == "CONFLICT"


def test_health_query_failure_returns_degraded_safe_response(app_client) -> None:
    client, _, fake = app_client
    fake.health_error = True

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "execution_mode": "mock",
        "worker_ok": False,
        "worker_ready": False,
        "worker_state": "UNKNOWN",
        "execution_enabled": False,
        "sync_status": "CONFLICT",
        "hyperliquid_domain": None,
    }


def test_health_reports_degraded_when_worker_is_not_ready(app_client) -> None:
    client, _, fake = app_client
    fake.ready_flag = False

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["worker_ok"] is True
    assert body["worker_ready"] is False
    assert body["worker_state"] == "NOT_READY"


def test_status_query_failure_before_any_mirror_does_not_write_flat(app_client) -> None:
    """Query failure with no prior row must present UNKNOWN and must not insert FLAT."""
    client, _, fake = app_client
    fake.get_position_error = True
    body = client.get("/api/status").json()["position"]
    assert body["side"] == PositionSide.UNKNOWN.value
    assert body["source"] == "unsynced"
    listed = client.get("/api/positions")
    assert listed.json() == []


def test_open_rejected_when_position_query_fails(app_client) -> None:
    client, _, fake = app_client
    start = client.post("/api/trading/start")
    assert start.json()["ok"] is True
    fake.get_position_error = True
    blocked = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert blocked.json()["accepted"] is False
    assert fake.place_calls == 0
    pos = client.get("/api/positions").json()
    assert len(pos) == 1
    assert pos[0]["source"] == "exchange_mirror"


def test_open_position_query_failure_enters_recovery(app_client) -> None:
    client, _, fake = app_client
    assert client.post("/api/trading/start").json()["ok"] is True
    fake.get_position_error = True

    blocked = client.post("/api/trading/signal", json={"signal": "LONG"})

    assert blocked.status_code == 200
    assert blocked.json()["accepted"] is False
    assert blocked.json()["reason"] == "exchange query failed"
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
    assert fake.place_calls == 0


def test_start_query_failure_enters_recovery_without_flat_row(app_client) -> None:
    client, _, fake = app_client
    fake.get_position_error = True
    start = client.post("/api/trading/start")
    assert start.json()["ok"] is False
    assert start.json()["reason"] == "exchange position query failed"
    status = client.get("/api/status").json()
    assert status["system_state"] == "RECOVERY"
    assert status["position"]["side"] == PositionSide.UNKNOWN.value
    assert client.get("/api/positions").json() == []
    fake.get_position_error = False
    blocked = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert blocked.json()["accepted"] is False
    assert fake.place_calls == 0


def test_start_rejects_exchange_open_orders_and_enters_recovery(app_client) -> None:
    client, _, fake = app_client
    fake.orders["0x" + "b" * 32] = OrderView(
        cloid="0x" + "b" * 32,
        exchange_oid="7",
        symbol="BTC-USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        status=OrderStatus.OPEN,
    )

    start = client.post("/api/trading/start")

    assert start.status_code == 200
    assert start.json() == {"ok": False, "reason": "exchange open orders present; recovery required"}
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
    assert fake.place_calls == 0


def test_open_rejects_exchange_open_orders_that_appear_after_start(app_client) -> None:
    client, _, fake = app_client
    assert client.post("/api/trading/start").json()["ok"] is True
    fake.orders["0x" + "c" * 32] = OrderView(
        cloid="0x" + "c" * 32,
        exchange_oid="8",
        symbol="BTC-USD",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        status=OrderStatus.OPEN,
    )

    blocked = client.post("/api/trading/signal", json={"signal": "LONG"})

    assert blocked.status_code == 200
    assert blocked.json()["accepted"] is False
    assert blocked.json()["reason"] == "exchange open orders present"
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
    assert fake.place_calls == 0


def test_status_unknown_exchange_position_enters_recovery(app_client) -> None:
    client, _, fake = app_client
    fake.positions["BTC-USD"] = PositionView(
        symbol="BTC-USD", side=PositionSide.UNKNOWN, size=Decimal("0")
    )

    body = client.get("/api/status").json()

    assert body["position"]["side"] == PositionSide.UNKNOWN.value
    assert body["system_state"] == "RECOVERY"
    assert body["trading_enabled"] is False


def test_start_rejects_unknown_exchange_position(app_client) -> None:
    client, _, fake = app_client
    fake.positions["BTC-USD"] = PositionView(
        symbol="BTC-USD", side=PositionSide.UNKNOWN, size=Decimal("0")
    )

    result = client.post("/api/trading/start")

    assert result.json() == {"ok": False, "reason": "exchange position query failed"}
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
    assert fake.place_calls == 0


def test_open_rejected_when_mirror_sync_returns_false(app_client) -> None:
    client, _, fake = app_client
    assert client.post("/api/trading/start").json()["ok"] is True

    async def failed_sync(*args, **kwargs):
        return False

    client.app.state.container.controller._sync_exchange_mirror = failed_sync
    blocked = client.post("/api/trading/signal", json={"signal": "LONG"})

    assert blocked.json()["accepted"] is False
    assert blocked.json()["reason"] == "exchange position query failed"
    assert fake.place_calls == 0
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
