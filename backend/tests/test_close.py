from __future__ import annotations

from app.core.enums import OrderStatus, PositionSide, SignalType


def test_long_then_close_goes_flat(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    opened = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert opened.json()["accepted"] is True
    assert client.get("/api/positions").json()[0]["side"] == PositionSide.LONG.value
    closed = client.post("/api/trading/signal", json={"signal": "CLOSE"})
    assert closed.json()["ok"] is True
    assert client.get("/api/positions").json()[0]["side"] == PositionSide.FLAT.value
    orders = client.get("/api/orders").json()
    close_orders = [item for item in orders if item["reduce_only"] is True]
    assert close_orders
    assert close_orders[0]["status"] == OrderStatus.FILLED.value
    assert fake.place_calls == 2


def test_short_then_close_goes_flat(app_client) -> None:
    client, _, _ = app_client
    client.post("/api/trading/start")
    opened = client.post("/api/trading/signal", json={"signal": "SHORT"})
    assert opened.json()["accepted"] is True
    closed = client.post("/api/trading/signal", json={"signal": "CLOSE"})
    assert closed.json()["ok"] is True
    assert client.get("/api/positions").json()[0]["side"] == PositionSide.FLAT.value


def test_close_does_not_auto_reverse_in_same_cycle(app_client) -> None:
    """CLOSE must not open the other side. Reverse while still in position is rejected."""
    client, _, fake = app_client
    client.post("/api/trading/start")
    client.post("/api/trading/signal", json={"signal": "LONG"})
    reverse_while_long = client.post("/api/trading/signal", json={"signal": "SHORT"})
    assert reverse_while_long.json()["accepted"] is False
    assert "reverse" in reverse_while_long.json()["reason"]
    assert fake.place_calls == 1
    closed = client.post("/api/trading/signal", json={"signal": SignalType.CLOSE.value})
    assert closed.json()["ok"] is True
    assert client.get("/api/positions").json()[0]["side"] == PositionSide.FLAT.value
    opening_after = [item for item in client.get("/api/orders").json() if item["reduce_only"] is False]
    assert len(opening_after) == 1


def test_close_and_stop_flattens_and_stops(app_client) -> None:
    client, _, _ = app_client
    client.post("/api/trading/start")
    client.post("/api/trading/signal", json={"signal": "LONG"})
    result = client.post("/api/trading/close-and-stop")
    assert result.json()["ok"] is True
    status = client.get("/api/status").json()
    assert status["position"]["side"] == PositionSide.FLAT.value
    assert status["system_state"] == "STOPPED"
    assert status["trading_enabled"] is False


def test_close_and_continue_stays_running(app_client) -> None:
    client, _, _ = app_client
    client.post("/api/trading/start")
    client.post("/api/trading/signal", json={"signal": "SHORT"})
    result = client.post("/api/trading/close-and-continue")
    assert result.json()["ok"] is True
    status = client.get("/api/status").json()
    assert status["position"]["side"] == PositionSide.FLAT.value
    assert status["system_state"] == "RUNNING"
    assert status["trading_enabled"] is True


def test_independent_open_after_close_is_not_auto_reverse(app_client) -> None:
    """A later independent SHORT after CLOSE+FLAT is a new open, not reverse-in-one-step."""
    client, _, fake = app_client
    client.post("/api/trading/start")
    client.post("/api/trading/signal", json={"signal": "LONG"})
    client.post("/api/trading/signal", json={"signal": "CLOSE"})
    later = client.post("/api/trading/signal", json={"signal": "SHORT"})
    assert later.json()["accepted"] is True
    assert client.get("/api/positions").json()[0]["side"] == PositionSide.SHORT.value
    assert fake.place_calls == 3
