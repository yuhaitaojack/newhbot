"""STEP 4 safety: Guard dual-lock, no hummingbot in Backend/Strategy, secrets stay untracked."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from app.config import WorkerConfig
from app.factory import build_runtime
from app.hummingbot_readonly import credentials_supplied, load_account_credentials

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_APP = Path(__file__).resolve().parents[1] / "app"
BACKEND_APP = REPO_ROOT / "backend" / "app"
STRATEGIES = REPO_ROOT / "strategies"


def test_factory_hyperliquid_enabled_requires_credentials(monkeypatch) -> None:
    monkeypatch.setattr("app.factory.load_account_credentials", lambda: None)
    with pytest.raises(RuntimeError, match="EXECUTION_ENABLED requires authenticated"):
        build_runtime(WorkerConfig(mode="hyperliquid", execution_enabled=True))


def test_factory_does_not_unconditionally_forbid_enabled_when_creds_present(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.factory.load_account_credentials",
        lambda: ("not-a-real-secret", "0xnotarealaddress"),
    )
    try:
        runtime = build_runtime(WorkerConfig(mode="hyperliquid", execution_enabled=True))
    except Exception as exc:
        assert "forbids EXECUTION_ENABLED" not in str(exc)
        return
    assert runtime.config.execution_enabled is True


def test_factory_mock_allows_execution_enabled_flag_without_live_place() -> None:
    runtime = build_runtime(WorkerConfig(mode="mock", execution_enabled=True))
    assert runtime.config.execution_enabled is True


def test_load_account_credentials_never_returns_empty_pair(monkeypatch) -> None:
    monkeypatch.delenv("HYPERLIQUID_PERPETUAL_SECRET_KEY", raising=False)
    monkeypatch.delenv("HYPERLIQUID_PERPETUAL_ADDRESS", raising=False)
    monkeypatch.delenv("HYPERLIQUID_PERPETUAL_SECRET_KEY_FILE", raising=False)
    monkeypatch.delenv("HYPERLIQUID_PERPETUAL_ADDRESS_FILE", raising=False)
    if not credentials_supplied():
        assert load_account_credentials() is None


def test_backend_and_strategy_do_not_import_hummingbot() -> None:
    roots = [BACKEND_APP]
    if STRATEGIES.is_dir():
        roots.append(STRATEGIES)
    hits: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "import hummingbot" in text or "from hummingbot" in text:
                hits.append(str(path.relative_to(REPO_ROOT)))
    assert hits == []


def test_backend_has_no_connector_write_calls() -> None:
    hits: list[str] = []
    for path in BACKEND_APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {
                "buy",
                "sell",
                "_place_order",
            }:
                hits.append(f"{path.name}:{node.lineno}:{node.attr}")
            if isinstance(node, ast.Name) and node.id in {"OrderExecutor", "PositionExecutor"}:
                hits.append(f"{path.name}:{node.lineno}:{node.id}")
    assert hits == []


def test_worker_production_adapter_does_not_call_buy_sell() -> None:
    adapter = (WORKER_APP / "hyperliquid_adapter.py").read_text(encoding="utf-8")
    assert "self.connector.buy(" not in adapter
    assert "self.connector.sell(" not in adapter
    bridge = (WORKER_APP / "hummingbot_readonly.py").read_text(encoding="utf-8")
    assert "disable_exchange_write_loops" in bridge
    assert "trading_required=True" in bridge


def test_env_and_secrets_are_gitignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-v", ".env", "secrets/x", "credentials/x", "docker-compose.override.yml"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert ".env" in combined
    assert "secrets" in combined


def test_no_literal_private_keys_in_tracked_sources() -> None:
    skip_parts = {".venv", "node_modules", "__pycache__", ".git", ".pytest_cache"}
    skip_names = {"test_step4_safety.py"}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".yml", ".yaml", ".md", ".json", ".toml"}:
            continue
        if path.name in skip_names:
            continue
        if any(part in skip_parts for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "BEGIN PRIVATE KEY" not in text
