from __future__ import annotations

from app.core.enums import OrderStatus


def test_timeout_after_accept_recovers_from_get_order(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.place_mode = "timeout_after_accept"
    result = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert result.json()["status"] == OrderStatus.OPEN.value
    assert result.json()["accepted"] is True
    assert fake.place_calls == 1


def test_unknown_reconciliation_sync_failure_stays_in_recovery(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.place_mode = "timeout_after_accept"
    fake.sync_error_after_timeout = True

    result = client.post("/api/trading/signal", json={"signal": "LONG"})

    assert result.json()["status"] == OrderStatus.OPEN.value
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
    assert fake.place_calls == 1
    fake.place_mode = "fill"
    blocked = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert blocked.json()["accepted"] is False
    assert fake.place_calls == 1


def test_absent_order_fill_and_position_clears_unknown(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.place_mode = "network_before_accept"
    result = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert result.json()["status"] == OrderStatus.REJECTED.value
    assert client.get("/api/status").json()["system_state"] != "RECOVERY"
    fake.place_mode = "fill"
    second = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert second.json()["accepted"] is True
    assert fake.place_calls == 2


def test_unconfirmed_query_stays_unknown_and_never_resubmits(app_client) -> None:
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.place_mode = "network_before_accept"
    fake.get_order_error = True
    result = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert result.json()["status"] == OrderStatus.UNKNOWN.value
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
    fake.place_mode = "fill"
    fake.get_order_error = False
    blocked = client.post("/api/trading/signal", json={"signal": "SHORT"})
    assert blocked.json()["accepted"] is False
    assert fake.place_calls == 1


def test_fill_without_order_stays_unknown(app_client) -> None:
    """No open order is not enough if a fill for that cloid exists."""
    client, _, fake = app_client
    client.post("/api/trading/start")
    fake.place_mode = "network_before_accept"
    fake.inject_fill_on_network_fail = True
    result = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert result.json()["status"] == OrderStatus.UNKNOWN.value
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
    assert fake.place_calls == 1
    fake.place_mode = "fill"
    fake.inject_fill_on_network_fail = False
    blocked = client.post("/api/trading/signal", json={"signal": "LONG"})
    assert blocked.json()["accepted"] is False
    assert fake.place_calls == 1
