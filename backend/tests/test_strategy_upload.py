from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.core.enums import OrderSide, OrderStatus, OrderType, PositionSide, SignalType, SystemState
from app.core.ids import new_cloid, new_id
from app.execution.protocol import OrderView, PositionView
from app.models import Order
from app.repositories import AuditRepository, SettingsRepository, StrategyRepository
from app.strategy.validate import MAX_STRATEGY_BYTES
from app.strategy.yaml_lite import parse_yaml_lite

REPO = Path(__file__).resolve().parents[2]
EMA_MANIFEST = REPO / "strategies" / "ema5break" / "manifest.yaml"

LEGAL_PY = """
def evaluate(snapshot):
    return {"signal": "HOLD", "reason": "idle"}
"""

LEGAL_YAML = """
name: custom_hold
version: "1.0.0"
symbol: BTC-USD
interval: 5m
parameters:
  - name: lookback
    type: int
    default: 20
"""


def _files(
    py: str | bytes = LEGAL_PY,
    yaml: str | bytes = LEGAL_YAML,
    py_name: str = "strategy.py",
    yaml_name: str = "manifest.yaml",
    extra: list[tuple] | None = None,
):
    py_bytes = py.encode("utf-8") if isinstance(py, str) else py
    yaml_bytes = yaml.encode("utf-8") if isinstance(yaml, str) else yaml
    items = [
        ("strategy.py", (py_name, py_bytes, "text/x-python")),
        ("manifest.yaml", (yaml_name, yaml_bytes, "application/x-yaml")),
    ]
    if extra:
        items.extend(extra)
    return items


def _reset_exec(fake) -> None:
    fake.place_calls = 0
    fake.cancel_calls = 0
    fake.set_leverage_calls = 0


def _call(client, async_fn):
    return client.portal.call(async_fn)


def test_yaml_lite_parses_ema5break_manifest() -> None:
    data = parse_yaml_lite(EMA_MANIFEST.read_text(encoding="utf-8"))
    assert data["name"] == "ema5break"
    assert str(data["version"]) == "1"
    assert data["symbol"] == "BTC-USD"
    assert data["interval"] == "5m"
    assert isinstance(data["parameters"], list)
    assert data["parameters"][0]["name"] == "ema_period"


def test_legal_strategy_upload_succeeds(app_client, tmp_path) -> None:
    client, app, fake = app_client
    _reset_exec(fake)
    marker = tmp_path / "executed_marker"
    py = f"""
open(r"{marker.as_posix()}", "w").write("executed")
def evaluate(snapshot):
    return {{"signal": "HOLD", "reason": "idle"}}
"""
    response = client.post("/api/strategy/upload", files=_files(py=py))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["activated"] is False
    assert body["duplicate"] is False
    assert body["name"] == "custom_hold"
    assert len(body["file_hash"]) == 64
    dest = Path(body["path"])
    if not dest.is_absolute():
        dest = Path(app.state.container.settings.strategies_dir) / body["file_hash"]
    assert (dest / "strategy.py").is_file()
    assert (dest / "manifest.yaml").is_file()
    assert not marker.exists()
    settings = client.get("/api/settings").json()
    assert settings["active_strategy"] == "ema5break"
    assert settings["system_state"] == SystemState.STOPPED.value
    assert fake.place_calls == 0
    assert fake.cancel_calls == 0
    assert fake.set_leverage_calls == 0


def test_missing_manifest_rejected(app_client, tmp_path) -> None:
    client, app, fake = app_client
    _reset_exec(fake)
    response = client.post(
        "/api/strategy/upload",
        files=[("strategy.py", ("strategy.py", LEGAL_PY.encode(), "text/x-python"))],
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert "manifest.yaml" in response.json()["reason"]
    assert client.get("/api/settings").json()["active_strategy"] == "ema5break"
    root = Path(app.state.container.settings.strategies_dir)
    assert not list(root.glob(".tmp-*"))
    assert fake.place_calls == 0


def test_illegal_manifest_rejected(app_client) -> None:
    client, _, fake = app_client
    _reset_exec(fake)
    bad = "this is not: [ yaml"
    response = client.post("/api/strategy/upload", files=_files(yaml=bad))
    assert response.status_code == 400
    assert response.json()["ok"] is False
    missing = """
name: custom_hold
version: "1.0.0"
"""
    response = client.post("/api/strategy/upload", files=_files(yaml=missing))
    assert response.status_code == 400
    reason = response.json()["reason"]
    assert "trading pair" in reason or "interval" in reason
    assert client.get("/api/settings").json()["active_strategy"] == "ema5break"
    assert fake.place_calls == 0


def test_dangerous_import_rejected(app_client) -> None:
    client, app, fake = app_client
    _reset_exec(fake)
    py = "import subprocess\n\ndef evaluate(snapshot):\n    return {'signal': 'HOLD', 'reason': 'x'}\n"
    response = client.post("/api/strategy/upload", files=_files(py=py))
    assert response.status_code == 400
    assert "dangerous import" in response.json()["reason"]
    assert client.get("/api/settings").json()["active_strategy"] == "ema5break"
    assert not list(Path(app.state.container.settings.strategies_dir).glob(".tmp-*"))
    assert fake.place_calls == 0


def test_direct_order_call_rejected(app_client) -> None:
    client, _, fake = app_client
    _reset_exec(fake)
    py = "def evaluate(snapshot):\n    place_order('BTC-USD')\n    return {'signal': 'LONG', 'reason': 'x'}\n"
    response = client.post("/api/strategy/upload", files=_files(py=py))
    assert response.status_code == 400
    assert "not allowed" in response.json()["reason"]
    assert client.get("/api/settings").json()["active_strategy"] == "ema5break"
    assert fake.place_calls == 0


def test_path_traversal_rejected(app_client) -> None:
    client, app, fake = app_client
    _reset_exec(fake)
    response = client.post(
        "/api/strategy/upload",
        files=_files(py_name="../../etc/passwd", yaml_name="../manifest.yaml"),
    )
    assert response.status_code == 400
    assert "path traversal" in response.json()["reason"]
    extra = client.post(
        "/api/strategy/upload",
        files=_files(extra=[("evil.py", ("evil.py", b"print(1)", "text/x-python"))]),
    )
    assert extra.status_code == 400
    assert "only strategy.py" in extra.json()["reason"]
    abs_path = client.post(
        "/api/strategy/upload",
        files=_files(py_name="C:/Windows/strategy.py"),
    )
    assert abs_path.status_code == 400
    assert "absolute" in abs_path.json()["reason"]
    root = Path(app.state.container.settings.strategies_dir)
    assert not list(root.glob(".tmp-*"))
    assert fake.place_calls == 0


def test_oversized_file_rejected(app_client) -> None:
    client, app, fake = app_client
    _reset_exec(fake)
    huge = b"# " + (b"a" * (MAX_STRATEGY_BYTES + 1))
    response = client.post("/api/strategy/upload", files=_files(py=huge))
    assert response.status_code == 400
    assert "too large" in response.json()["reason"]
    assert not list(Path(app.state.container.settings.strategies_dir).glob(".tmp-*"))
    assert fake.place_calls == 0


def test_duplicate_hash_does_not_create_second_version(app_client) -> None:
    client, app, fake = app_client
    _reset_exec(fake)
    first = client.post("/api/strategy/upload", files=_files())
    assert first.status_code == 200
    file_hash = first.json()["file_hash"]
    second = client.post("/api/strategy/upload", files=_files())
    assert second.status_code == 200
    assert second.json()["ok"] is True
    assert second.json()["duplicate"] is True
    assert second.json()["file_hash"] == file_hash

    async def _count():
        async with app.state.container.session_factory() as session:
            return await StrategyRepository(session).count_by_hash(file_hash)

    assert _call(client, _count) == 1
    versions = [item for item in client.get("/api/strategy/versions").json() if item["file_hash"] == file_hash]
    assert len(versions) == 1
    dest = Path(app.state.container.settings.strategies_dir) / file_hash
    assert dest.is_dir()
    assert not list(Path(app.state.container.settings.strategies_dir).glob(".tmp-*"))
    assert fake.place_calls == 0


def test_running_cannot_activate(app_client) -> None:
    client, _, fake = app_client
    uploaded = client.post("/api/strategy/upload", files=_files())
    file_hash = uploaded.json()["file_hash"]
    started = client.post("/api/trading/start")
    assert started.json()["ok"] is True
    _reset_exec(fake)
    refused = client.post("/api/strategy/activate", json={"file_hash": file_hash})
    assert refused.status_code == 200
    assert refused.json()["ok"] is False
    assert "RUNNING" in refused.json()["reason"]
    status = client.get("/api/status").json()
    assert status["system_state"] == SystemState.RUNNING.value
    assert status["settings"]["active_strategy"] == "ema5break"
    assert fake.place_calls == 0
    assert fake.cancel_calls == 0
    assert fake.set_leverage_calls == 0


def test_open_position_cannot_activate(app_client) -> None:
    client, _, fake = app_client
    file_hash = client.post("/api/strategy/upload", files=_files()).json()["file_hash"]
    fake.positions["BTC-USD"] = PositionView(
        symbol="BTC-USD", side=PositionSide.LONG, size=Decimal("0.001")
    )
    _reset_exec(fake)
    refused = client.post("/api/strategy/activate", json={"file_hash": file_hash})
    assert refused.json()["ok"] is False
    assert "position" in refused.json()["reason"]
    assert client.get("/api/settings").json()["active_strategy"] == "ema5break"
    assert client.get("/api/status").json()["system_state"] == SystemState.STOPPED.value
    assert fake.place_calls == 0
    assert fake.cancel_calls == 0
    assert fake.set_leverage_calls == 0


def test_activate_position_query_failure_enters_recovery(app_client) -> None:
    client, _, fake = app_client
    file_hash = client.post("/api/strategy/upload", files=_files()).json()["file_hash"]
    fake.get_position_error = True

    refused = client.post("/api/strategy/activate", json={"file_hash": file_hash})

    assert refused.status_code == 200
    assert refused.json()["ok"] is False
    assert "position query failed" in refused.json()["reason"]
    assert client.get("/api/status").json()["system_state"] == SystemState.RECOVERY.value
    assert fake.place_calls == 0


def test_dunder_reflection_rejected(app_client) -> None:
    client, _, fake = app_client
    _reset_exec(fake)
    py = "def evaluate(snapshot):\n    return ().__class__.__base__.__subclasses__()\n"

    response = client.post("/api/strategy/upload", files=_files(py=py))

    assert response.status_code == 400
    assert "dunder access" in response.json()["reason"]
    assert fake.place_calls == 0


def test_activate_foreign_exchange_position_enters_recovery(app_client) -> None:
    client, _, fake = app_client
    file_hash = client.post("/api/strategy/upload", files=_files()).json()["file_hash"]
    fake.positions["ETH-USD"] = PositionView(
        symbol="ETH-USD", side=PositionSide.LONG, size=Decimal("0.001")
    )

    refused = client.post("/api/strategy/activate", json={"file_hash": file_hash})

    assert refused.json() == {
        "ok": False,
        "reason": "cannot activate while an exchange position is open",
    }
    assert client.get("/api/status").json()["system_state"] == SystemState.RECOVERY.value
    assert fake.place_calls == 0


def test_activate_exchange_open_orders_enters_recovery(app_client) -> None:
    client, _, fake = app_client
    file_hash = client.post("/api/strategy/upload", files=_files()).json()["file_hash"]
    fake.orders["0x" + "d" * 32] = OrderView(
        cloid="0x" + "d" * 32,
        exchange_oid="9",
        symbol="ETH-USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        status=OrderStatus.OPEN,
    )

    refused = client.post("/api/strategy/activate", json={"file_hash": file_hash})

    assert refused.json() == {
        "ok": False,
        "reason": "cannot activate while exchange open orders are present",
    }
    assert client.get("/api/status").json()["system_state"] == SystemState.RECOVERY.value
    assert fake.place_calls == 0


def test_recovery_cannot_activate(app_client) -> None:
    client, app, fake = app_client
    file_hash = client.post("/api/strategy/upload", files=_files()).json()["file_hash"]

    async def _recover():
        async with app.state.container.session_factory() as session:
            await app.state.container.recovery.enter_recovery(session, "step7_test")
            await session.commit()

    _call(client, _recover)
    _reset_exec(fake)
    refused = client.post("/api/strategy/activate", json={"file_hash": file_hash})
    assert refused.json()["ok"] is False
    assert "RECOVERY" in refused.json()["reason"]
    assert client.get("/api/settings").json()["active_strategy"] == "ema5break"
    assert fake.place_calls == 0


def test_unknown_order_cannot_activate(app_client) -> None:
    client, app, fake = app_client
    file_hash = client.post("/api/strategy/upload", files=_files()).json()["file_hash"]

    async def _plant():
        async with app.state.container.session_factory() as session:
            settings = await SettingsRepository(session).get()
            session.add(
                Order(
                    id=new_id(),
                    intent_id=new_id(),
                    request_id=new_id(),
                    cloid=new_cloid(),
                    symbol=settings.trading_pair,
                    side=OrderSide.BUY.value,
                    order_type=OrderType.MARKET.value,
                    quantity=Decimal("1"),
                    reduce_only=False,
                    status=OrderStatus.UNKNOWN.value,
                )
            )
            await session.commit()

    _call(client, _plant)
    _reset_exec(fake)
    refused = client.post("/api/strategy/activate", json={"file_hash": file_hash})
    assert refused.json()["ok"] is False
    assert "UNKNOWN" in refused.json()["reason"] or "unresolved" in refused.json()["reason"]
    assert client.get("/api/settings").json()["active_strategy"] == "ema5break"
    assert fake.place_calls == 0
    assert fake.cancel_calls == 0
    assert fake.set_leverage_calls == 0


def test_activate_stays_stopped_and_writes_audit(app_client) -> None:
    client, app, fake = app_client
    uploaded = client.post("/api/strategy/upload", files=_files())
    file_hash = uploaded.json()["file_hash"]
    _reset_exec(fake)
    activated = client.post("/api/strategy/activate", json={"file_hash": file_hash})
    assert activated.status_code == 200
    body = activated.json()
    assert body["ok"] is True
    assert body["state"] == SystemState.STOPPED.value
    assert body["trading_enabled"] is False
    assert body["name"] == "custom_hold"
    status = client.get("/api/status").json()
    assert status["system_state"] == SystemState.STOPPED.value
    assert status["trading_enabled"] is False
    assert status["settings"]["active_strategy"] == "custom_hold"
    assert status["settings"]["active_strategy_version"] == "1.0.0"
    events = client.get("/api/events").json()
    assert any(item["event_type"] == "strategy_status" for item in events)
    async def _audit():
        async with app.state.container.session_factory() as session:
            rows = await AuditRepository(session).list_recent()
            return [item.action for item in rows]

    actions = _call(client, _audit)
    assert "strategy_activate" in actions
    assert "strategy_upload" in actions
    assert fake.place_calls == 0
    assert fake.cancel_calls == 0
    assert fake.set_leverage_calls == 0


def test_settings_cannot_bypass_strategy_activation(app_client) -> None:
    client, _, _ = app_client
    before = client.get("/api/settings").json()
    response = client.put(
        "/api/settings",
        json={"active_strategy": "forged", "active_strategy_version": "9.9.9", "leverage": 4},
    )

    assert response.status_code == 200
    after = response.json()
    assert after["active_strategy"] == before["active_strategy"]
    assert after["active_strategy_version"] == before["active_strategy_version"]
    assert after["leverage"] == 4


def test_strategy_tick_evaluates_active_version_and_routes_hold(app_client) -> None:
    client, _, fake = app_client
    uploaded = client.post("/api/strategy/upload", files=_files())
    activated = client.post("/api/strategy/activate", json={"file_hash": uploaded.json()["file_hash"]})
    assert activated.json()["ok"] is True

    result = client.post("/api/strategy/tick", json={"snapshot": {"bars": []}})

    assert result.status_code == 200
    body = result.json()
    assert body["signal"] == "HOLD"
    assert body.get("ok") is True, body
    assert body["controller"]["accepted"] is True
    assert fake.place_calls == 0


def test_strategy_tick_open_signal_is_rejected_while_stopped(app_client) -> None:
    client, _, fake = app_client
    strategy = """
def evaluate(snapshot):
    return {"signal": "LONG", "reason": "open-test"}
"""
    uploaded = client.post("/api/strategy/upload", files=_files(py=strategy))
    assert client.post("/api/strategy/activate", json={"file_hash": uploaded.json()["file_hash"]}).json()["ok"] is True

    result = client.post("/api/strategy/tick", json={"snapshot": {"bars": []}})

    assert result.status_code == 200
    assert result.json()["signal"] == "LONG"
    assert result.json()["controller"]["accepted"] is False
    assert "not RUNNING" in result.json()["controller"]["reason"]
    assert fake.place_calls == 0


def test_strategy_tick_open_signal_is_rejected_in_recovery(app_client) -> None:
    client, app, fake = app_client

    async def mark_recovery() -> None:
        async with app.state.container.session_factory() as session:
            settings = await SettingsRepository(session).get()
            settings.system_state = SystemState.RECOVERY.value
            settings.trading_enabled = False
            await session.commit()

    strategy = """
def evaluate(snapshot):
    return {"signal": "LONG", "reason": "recovery-open-test"}
"""
    uploaded = client.post("/api/strategy/upload", files=_files(py=strategy))
    assert client.post("/api/strategy/activate", json={"file_hash": uploaded.json()["file_hash"]}).json()["ok"] is True
    _call(client, mark_recovery)

    result = client.post("/api/strategy/tick", json={"snapshot": {"bars": []}})

    assert result.status_code == 200
    assert result.json()["signal"] == "LONG"
    assert result.json()["controller"]["accepted"] is False
    assert "recovery" in result.json()["controller"]["reason"]
    assert fake.place_calls == 0


def test_strategy_tick_close_signal_is_rejected_in_recovery(app_client) -> None:
    client, app, fake = app_client
    strategy = """
def evaluate(snapshot):
    return {"signal": "CLOSE", "reason": "recovery-close-test"}
"""
    uploaded = client.post("/api/strategy/upload", files=_files(py=strategy))
    assert client.post("/api/strategy/activate", json={"file_hash": uploaded.json()["file_hash"]}).json()["ok"] is True
    fake.positions["BTC-USD"] = PositionView(
        symbol="BTC-USD", side=PositionSide.LONG, size=Decimal("1"), entry_price=Decimal("100")
    )

    async def mark_recovery() -> None:
        async with app.state.container.session_factory() as session:
            settings = await SettingsRepository(session).get()
            settings.system_state = SystemState.RECOVERY.value
            settings.trading_enabled = False
            await session.commit()

    _call(client, mark_recovery)
    result = client.post("/api/strategy/tick", json={"snapshot": {"bars": []}})

    assert result.status_code == 200
    assert result.json()["signal"] == "CLOSE"
    assert result.json()["controller"]["accepted"] is False
    assert "recovery" in result.json()["controller"]["reason"]
    assert fake.place_calls == 0


def test_strategy_page_parameters_match_active_strategy_version(app_client) -> None:
    client, _, _ = app_client
    second_yaml = LEGAL_YAML.replace('version: "1.0.0"', 'version: "2.0.0"').replace(
        "name: lookback", "name: fast_period"
    )

    first = client.post("/api/strategy/upload", files=_files())
    second = client.post(
        "/api/strategy/upload",
        files=_files(py=LEGAL_PY + "\n# version two\n", yaml=second_yaml),
    )
    assert first.json()["ok"] is True
    assert second.json()["ok"] is True

    activated = client.post("/api/strategy/activate", json={"file_hash": first.json()["file_hash"]})
    assert activated.json()["ok"] is True

    strategy = client.get("/api/strategy").json()
    assert strategy["active_strategy"] == "custom_hold"
    assert strategy["active_strategy_version"] == "1.0.0"
    assert [item["name"] for item in strategy["parameters"]] == ["lookback"]


def test_active_strategy_parameter_can_be_enabled_and_persisted(app_client) -> None:
    client, _, _ = app_client
    yaml = LEGAL_YAML.replace("default: 20", "default: 20\n    min: 1\n    max: 100")
    uploaded = client.post("/api/strategy/upload", files=_files(yaml=yaml)).json()
    assert client.post("/api/strategy/activate", json={"file_hash": uploaded["file_hash"]}).json()["ok"] is True
    parameter = client.get("/api/strategy").json()["parameters"][0]
    assert parameter["enabled"] is False
    assert parameter["effective_value"] == "20"

    updated = client.put(
        f"/api/strategy/parameters/{parameter['id']}",
        json={"enabled": True, "current_value": "40"},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is True
    assert updated.json()["effective_value"] == "40"
    assert client.get("/api/strategy").json()["parameters"][0]["effective_value"] == "40"

    invalid = client.put(
        f"/api/strategy/parameters/{parameter['id']}",
        json={"current_value": "101"},
    )
    assert invalid.status_code == 422


def test_enabled_parameter_reaches_strategy_runtime_snapshot(app_client) -> None:
    client, _, _ = app_client
    strategy = """
def evaluate(snapshot):
    return {"signal": "HOLD", "reason": snapshot["parameters"]["lookback"]}
"""
    uploaded = client.post("/api/strategy/upload", files=_files(py=strategy)).json()
    assert client.post("/api/strategy/activate", json={"file_hash": uploaded["file_hash"]}).json()["ok"] is True
    parameter = client.get("/api/strategy").json()["parameters"][0]
    updated = client.put(
        f"/api/strategy/parameters/{parameter['id']}",
        json={"enabled": True, "current_value": "40"},
    )
    assert updated.status_code == 200

    tick = client.post("/api/strategy/tick", json={"snapshot": {"bars": []}})
    assert tick.status_code == 200
    assert tick.json()["signal"] == "HOLD"
    assert tick.json()["reason"] == "40"


def test_strategy_tick_position_query_failure_enters_recovery(app_client) -> None:
    client, _, fake = app_client
    fake.get_position_error = True

    result = client.post("/api/strategy/tick", json={"snapshot": {"bars": []}})

    assert result.status_code == 200
    body = result.json()
    assert body == {
        "ok": False,
        "signal": "HOLD",
        "reason": "strategy_tick_position_query_failed:TimeoutError",
        "controller": {"accepted": False, "reason": "recovery required"},
    }
    assert client.get("/api/status").json()["system_state"] == "RECOVERY"
    assert fake.place_calls == 0


def test_strategy_tick_unknown_position_enters_recovery(app_client) -> None:
    client, _, fake = app_client
    fake.positions["BTC-USD"] = PositionView(
        symbol="BTC-USD", side=PositionSide.UNKNOWN, size=Decimal("0")
    )

    result = client.post("/api/strategy/tick", json={"snapshot": {"bars": []}})

    assert result.status_code == 200
    assert result.json() == {
        "ok": False,
        "signal": SignalType.HOLD.value,
        "reason": "strategy_tick_position_unknown",
        "controller": {"accepted": False, "reason": "recovery required"},
    }
    assert client.get("/api/status").json()["system_state"] == SystemState.RECOVERY.value
    assert fake.place_calls == 0


def test_strategy_tick_runtime_failure_returns_hold_without_order(app_client) -> None:
    client, app, fake = app_client
    uploaded = client.post("/api/strategy/upload", files=_files())
    assert client.post("/api/strategy/activate", json={"file_hash": uploaded.json()["file_hash"]}).json()["ok"] is True

    async def fail(*args, **kwargs):
        raise RuntimeError("runtime failed")

    app.state.container.strategy_runtime.evaluate = fail
    result = client.post("/api/strategy/tick", json={"snapshot": {"bars": []}})

    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert result.json()["signal"] == "HOLD"
    assert "runtime failed" in result.json()["reason"]
    assert fake.place_calls == 0


def test_direct_signal_injection_is_blocked_outside_mock(app_client) -> None:
    client, app, _ = app_client
    app.state.container.settings.execution_mode = "hyperliquid"
    app.state.container.settings.control_api_token = "test-token"

    response = client.post(
        "/api/trading/signal", json={"signal": "HOLD"}, headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 403


def test_non_mock_mutations_require_control_token(app_client) -> None:
    client, app, _ = app_client
    app.state.container.settings.execution_mode = "hyperliquid"
    app.state.container.settings.control_api_token = "test-token"

    refused = client.post("/api/trading/stop")
    accepted = client.post("/api/trading/stop", headers={"Authorization": "Bearer test-token"})

    assert refused.status_code == 401
    assert accepted.status_code == 200


def test_preflight_is_read_only_and_reports_mock_no_go(app_client) -> None:
    client, _, fake = app_client
    before = (fake.place_calls, fake.cancel_calls, fake.set_leverage_calls)

    response = client.get("/api/preflight")
    body = response.json()

    assert response.status_code == 200
    assert body["ready_for_live"] is False
    assert "execution mode is not hyperliquid" in body["reasons"]
    assert "worker execution is disabled" in body["reasons"]
    assert (fake.place_calls, fake.cancel_calls, fake.set_leverage_calls) == before


def test_preflight_rejects_non_positive_available_balance(app_client) -> None:
    client, _, fake = app_client
    fake.equity = 100
    fake.available = 0

    response = client.get("/api/preflight")
    body = response.json()

    assert response.status_code == 200
    assert body["available"] == "0"
    assert "exchange available balance is not positive" in body["reasons"]


def test_live_candle_source_is_not_reached_from_mock(app_client) -> None:
    client, _, fake = app_client

    response = client.get("/api/market/candles", params={"symbol": "BTC-USD"})

    assert response.status_code == 403
    assert fake.place_calls == 0


def test_live_candle_query_failure_returns_503(app_client) -> None:
    client, app, fake = app_client
    app.state.container.settings.execution_mode = "hyperliquid"
    fake.get_candles_error = True

    response = client.get("/api/market/candles", params={"symbol": "BTC-USD"})

    assert response.status_code == 503
    assert response.json()["detail"] == "candle source unavailable: TimeoutError"
    assert fake.place_calls == 0


def test_strategy_loop_is_explicit_and_stoppable(app_client) -> None:
    client, _, fake = app_client
    fake.candles = [{"timestamp": 1, "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}]
    uploaded = client.post("/api/strategy/upload", files=_files())
    assert client.post("/api/strategy/activate", json={"file_hash": uploaded.json()["file_hash"]}).json()["ok"] is True
    assert client.post("/api/trading/start").json()["ok"] is True

    started = client.post("/api/strategy/loop/start")
    running = client.get("/api/strategy/loop").json()
    stopped = client.post("/api/strategy/loop/stop")

    assert started.json()["running"] is True
    assert running["running"] is True
    assert stopped.json()["running"] is False


def test_strategy_loop_cannot_start_while_trading_is_stopped(app_client) -> None:
    client, _, _ = app_client
    response = client.post("/api/strategy/loop/start")
    assert response.status_code == 409
    assert response.json()["detail"] == "strategy loop requires trading state RUNNING"
    assert client.get("/api/strategy/loop").json()["running"] is False

def test_upload_and_activate_never_call_execution_writes(app_client) -> None:
    client, _, fake = app_client
    _reset_exec(fake)
    uploaded = client.post("/api/strategy/upload", files=_files())
    client.post("/api/strategy/activate", json={"file_hash": uploaded.json()["file_hash"]})
    assert fake.place_calls == 0
    assert fake.cancel_calls == 0
    assert fake.set_leverage_calls == 0
