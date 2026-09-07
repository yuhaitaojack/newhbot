from __future__ import annotations

from decimal import Decimal

from app.core.enums import OrderStatus, PositionSide, SignalType
from app.execution.protocol import PositionView


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


def test_close_and_continue_restarts_stopped_strategy_loop(app_client) -> None:
    client, _, _ = app_client
    client.post("/api/trading/start")
    client.post("/api/strategy/loop/stop")
    assert client.get("/api/strategy/loop").json()["running"] is False

    result = client.post("/api/trading/close-and-continue")

    assert result.json()["ok"] is True
    assert client.get("/api/status").json()["system_state"] == "RUNNING"
    assert client.get("/api/strategy/loop").json()["running"] is True


def test_close_sync_failure_enters_recovery_and_requires_confirmation(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    assert client.post("/api/trading/signal", json={"signal": "LONG"}).json()["accepted"] is True
    fake.get_balance_error = True

    result = client.post("/api/trading/close-and-continue")

    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert result.json()["reason"] == "close confirmation required"
    status = client.get("/api/status").json()
    assert status["system_state"] == "RECOVERY"
    assert status["strategy_loop_running"] is False
    assert fake.place_calls == 2


def test_partial_close_confirmation_enters_recovery_and_does_not_continue(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    assert client.post("/api/trading/signal", json={"signal": "LONG"}).json()["accepted"] is True
    fake.place_mode = "partial"

    result = client.post("/api/trading/close-and-continue")

    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert result.json()["reason"] == "close confirmation required"
    status = client.get("/api/status").json()
    assert status["system_state"] == "RECOVERY"
    assert status["strategy_loop_running"] is False
    assert status["position"]["side"] == PositionSide.LONG.value
    assert fake.place_calls == 2


def test_close_cancel_failure_enters_recovery_without_submitting_close(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.place_mode = "timeout_after_accept"
    pending = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert pending.json()["status"] == OrderStatus.OPEN.value
    fake.positions["BTC-USD"] = PositionView(symbol="BTC-USD", side=PositionSide.LONG, size="1")
    fake.cancel_order_error = True

    result = client.post("/api/trading/close-and-continue")

    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert result.json()["reason"] == "open order cancellation unconfirmed; recovery required"
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
    assert fake.place_calls == 1


def test_close_unknown_exchange_position_enters_recovery_without_order(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.positions["BTC-USD"] = PositionView(
        symbol="BTC-USD", side=PositionSide.UNKNOWN, size=Decimal("1")
    )

    result = client.post("/api/trading/signal", json={"signal": "CLOSE"})

    assert result.json()["ok"] is False
    assert result.json()["reason"] == "exchange position unknown; recovery required"
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
    assert fake.place_calls == 0


def test_emergency_cancel_failure_does_not_submit_close(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.place_mode = "timeout_after_accept"
    pending = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert pending.json()["status"] == OrderStatus.OPEN.value
    fake.positions["BTC-USD"] = PositionView(symbol="BTC-USD", side=PositionSide.LONG, size="1")
    fake.cancel_order_error = True

    result = client.post("/api/trading/emergency-stop")

    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert result.json()["reason"] == "order cancellation unconfirmed; recovery required"
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
    assert client.get("/api/status").json()["estop"] is True
    assert fake.place_calls == 1


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


def test_market_open_reported_open_but_position_filled_allows_next_roundtrip(app_client) -> None:
    """IOC OPEN acknowledgement is finalized from exchange position confirmation."""
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.place_mode = "open_but_filled_position"

    first = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert first.json()["accepted"] is True
    assert first.json()["status"] == OrderStatus.FILLED.value
    assert client.post("/api/trading/signal", json={"signal": "CLOSE"}).json()["ok"] is True

    second = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert second.json()["accepted"] is True
    assert second.json()["status"] == OrderStatus.FILLED.value
    orders = client.get("/api/orders").json()
    assert len([item for item in orders if item["reduce_only"] is False]) == 2
