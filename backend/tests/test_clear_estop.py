from __future__ import annotations

from decimal import Decimal

from app.core.enums import OrderSide, OrderStatus, OrderType, PositionSide
from app.execution.protocol import OrderView, PositionView


def _latch_estop(client) -> None:
    client.post("/api/trading/start")
    result = client.post("/api/trading/emergency-stop")
    assert result.status_code == 200
    status = client.get("/api/status").json()
    assert status["estop"] is True
    assert status["trading_enabled"] is False
    assert status["system_state"] == "STOPPED"
    assert status["position"]["side"] == PositionSide.FLAT.value


def test_clear_estop_when_flat_and_no_orders(app_client) -> None:
    client, _, fake = app_client
    _latch_estop(client)
    fake.place_calls = 0
    fake.cancel_calls = 0
    fake.set_leverage_calls = 0

    cleared = client.post("/api/trading/clear-estop")
    assert cleared.status_code == 200
    body = cleared.json()
    assert body["ok"] is True
    assert body["estop"] is False
    assert body["state"] == "STOPPED"
    assert body["reason"] == "estop_cleared_still_stopped"

    status = client.get("/api/status").json()
    assert status["estop"] is False
    assert status["trading_enabled"] is False
    assert status["system_state"] == "STOPPED"
    assert fake.place_calls == 0
    assert fake.cancel_calls == 0
    assert fake.set_leverage_calls == 0

    events = client.get("/api/events").json()
    estop_events = [item for item in events if item["event_type"] == "estop"]
    assert estop_events
    assert any("cleared" in item["payload_json"] for item in estop_events)


def test_clear_estop_rejects_open_position(app_client) -> None:
    client, _, fake = app_client
    _latch_estop(client)
    fake.positions["BTC-USD"] = PositionView(
        symbol="BTC-USD", side=PositionSide.LONG, size=Decimal("0.001")
    )
    fake.place_calls = 0
    fake.cancel_calls = 0
    fake.set_leverage_calls = 0

    refused = client.post("/api/trading/clear-estop")
    assert refused.json()["ok"] is False
    assert "FLAT" in refused.json()["reason"]
    assert client.get("/api/status").json()["estop"] is True
    assert client.get("/api/status").json()["system_state"] in {"STOPPED", "RECOVERY"}
    assert fake.place_calls == 0
    assert fake.cancel_calls == 0
    assert fake.set_leverage_calls == 0


def test_clear_estop_rejects_open_orders(app_client) -> None:
    client, _, fake = app_client
    _latch_estop(client)
    fake.orders["0x" + "a" * 32] = OrderView(
        cloid="0x" + "a" * 32,
        exchange_oid="1",
        symbol="BTC-USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.001"),
        status=OrderStatus.OPEN,
    )
    refused = client.post("/api/trading/clear-estop")
    assert refused.json()["ok"] is False
    assert "open orders" in refused.json()["reason"]
    assert client.get("/api/status").json()["estop"] is True


def test_clear_estop_rejects_unknown_order(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.place_mode = "network_before_accept"
    fake.get_order_error = True
    unknown = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert unknown.json()["status"] == OrderStatus.UNKNOWN.value
    fake.place_mode = "fill"
    fake.get_order_error = False
    estop = client.post("/api/trading/emergency-stop")
    assert estop.status_code == 200
    assert client.get("/api/status").json()["estop"] is True
    assert any(item["status"] == OrderStatus.UNKNOWN.value for item in client.get("/api/orders").json())

    fake.place_calls = 0
    fake.cancel_calls = 0
    fake.set_leverage_calls = 0
    refused = client.post("/api/trading/clear-estop")
    assert refused.json()["ok"] is False
    assert "UNKNOWN" in refused.json()["reason"] or "unresolved" in refused.json()["reason"]
    assert client.get("/api/status").json()["estop"] is True
    assert fake.place_calls == 0
    assert fake.cancel_calls == 0
    assert fake.set_leverage_calls == 0


def test_clear_estop_rejects_foreign_position(app_client) -> None:
    client, _, fake = app_client
    _latch_estop(client)
    fake.positions["ETH-USD"] = PositionView(
        symbol="ETH-USD", side=PositionSide.SHORT, size=Decimal("0.01")
    )
    refused = client.post("/api/trading/clear-estop")
    assert refused.json()["ok"] is False
    assert "foreign" in refused.json()["reason"]
    assert client.get("/api/status").json()["estop"] is True


def test_clear_estop_does_not_start_strategy(app_client) -> None:
    client, _, _ = app_client
    _latch_estop(client)
    before = {item["id"] for item in client.get("/api/events").json()}
    cleared = client.post("/api/trading/clear-estop")
    assert cleared.json()["ok"] is True
    assert cleared.json()["state"] == "STOPPED"
    status = client.get("/api/status").json()
    assert status["system_state"] == "STOPPED"
    assert status["trading_enabled"] is False
    new_events = [item for item in client.get("/api/events").json() if item["id"] not in before]
    assert not any(item["event_type"] == "strategy_status" for item in new_events)
    assert not any('"to": "RUNNING"' in item["payload_json"] for item in new_events)


def test_clear_estop_does_not_call_place_cancel_or_leverage(app_client) -> None:
    client, _, fake = app_client
    _latch_estop(client)
    fake.place_calls = 0
    fake.cancel_calls = 0
    fake.set_leverage_calls = 0
    client.post("/api/trading/clear-estop")
    assert fake.place_calls == 0
    assert fake.cancel_calls == 0
    assert fake.set_leverage_calls == 0


def test_settings_api_cannot_clear_estop(app_client) -> None:
    client, _, _ = app_client
    _latch_estop(client)
    bypass = client.put("/api/settings", json={"estop": False, "leverage": 3})
    assert bypass.status_code == 200
    body = bypass.json()
    assert body["estop"] is True
    assert client.get("/api/status").json()["estop"] is True
    assert client.get("/api/settings").json()["estop"] is True


def test_clear_estop_rejected_when_not_latched(app_client) -> None:
    client, _, fake = app_client
    refused = client.post("/api/trading/clear-estop")
    assert refused.json()["ok"] is False
    assert "not latched" in refused.json()["reason"]
    assert fake.place_calls == 0


def test_clear_estop_health_query_failure_enters_recovery(app_client) -> None:
    client, _, fake = app_client
    _latch_estop(client)
    fake.health_error = True

    refused = client.post("/api/trading/clear-estop")

    assert refused.status_code == 200
    assert refused.json()["ok"] is False
    assert refused.json()["reason"] == "worker health query failed: TimeoutError"
    assert refused.json()["estop"] is True
    assert refused.json()["state"] == "RECOVERY"
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
    assert fake.place_calls == 0
    assert fake.cancel_calls == 0
