"""REAL CONNECTOR tests for PHASE 4.

Requires the official image hummingbot/hummingbot:version-2.16.0.
Skipped when Docker or the image is absent. Never mixed with FakeConnector.
Never calls buy/sell/_place_order/cancel/updateLeverage.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.connector_bridge import try_load_hummingbot_connector_class
from app.hummingbot_readonly import instantiate_readonly, try_load_hummingbot_connector_class as load_cls
from app.readonly_guard import ReadOnlyGuard, ReadOnlyViolation

WORKER_ROOT = Path(__file__).resolve().parents[1]
PROBE = WORKER_ROOT / "scripts" / "phase4_readonly_probe.py"
RUNTIME_PROBE = WORKER_ROOT / "scripts" / "phase4_readonly_runtime_probe.py"
IMAGE = "hummingbot/hummingbot:version-2.16.0"


def _docker() -> str | None:
    found = shutil.which("docker")
    if found:
        return found
    user_install = Path.home() / "AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe"
    if user_install.is_file():
        return str(user_install)
    return None


def _image_present(docker: str) -> bool:
    result = subprocess.run(
        [docker, "image", "inspect", IMAGE],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _run_in_hummingbot(docker: str, script: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "-e",
            "PYTHONPATH=/home/hummingbot",
            "-w",
            "/home/hummingbot",
            "-v",
            f"{script.resolve().as_posix()}:/tmp/probe.py:ro",
            "--entrypoint",
            "/opt/conda/envs/hummingbot/bin/python",
            IMAGE,
            "/tmp/probe.py",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def test_real_connector_local_import_is_optional() -> None:
    cls = try_load_hummingbot_connector_class()
    assert cls is load_cls()
    if cls is None:
        pytest.skip("REAL CONNECTOR not importable on this interpreter")
    connector = instantiate_readonly(cls, ["BTC-USD"])
    guard = ReadOnlyGuard(connector)
    assert connector.is_trading_required is False
    assert connector.authenticator is None
    modes = [str(item) for item in connector.supported_position_modes()]
    assert any("ONEWAY" in item.upper() for item in modes)
    assert not any("HEDGE" in item.upper() for item in modes)
    with pytest.raises(ReadOnlyViolation):
        guard.buy("BTC-USD", 1)
    with pytest.raises(ReadOnlyViolation):
        guard.sell("BTC-USD", 1)
    with pytest.raises(ReadOnlyViolation):
        guard._place_order()
    with pytest.raises(ReadOnlyViolation):
        guard.cancel("0x" + "a" * 32)
    with pytest.raises(ReadOnlyViolation):
        guard.set_leverage("BTC-USD", 2)
    assert "buy" in guard.violations


def test_real_connector_docker_import_instantiate_readonly() -> None:
    docker = _docker()
    if docker is None:
        pytest.skip("REAL CONNECTOR Docker not available")
    if not _image_present(docker):
        pytest.skip(f"REAL CONNECTOR image {IMAGE} not present")
    result = _run_in_hummingbot(docker, PROBE)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["import_ok"] is True
    assert payload["instantiate_ok"] is True
    assert payload["trading_required"] is False
    assert payload["authenticator_is_none"] is True
    assert payload["oneway_present"] is True
    assert payload["hedge_present"] is False
    assert payload["forbidden_called"] == []
    assert "trading_required" in payload["constructor_params"]


def test_real_connector_docker_public_rules_and_readonly_network() -> None:
    docker = _docker()
    if docker is None:
        pytest.skip("REAL CONNECTOR Docker not available")
    if not _image_present(docker):
        pytest.skip(f"REAL CONNECTOR image {IMAGE} not present")
    result = _run_in_hummingbot(docker, RUNTIME_PROBE, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout[result.stdout.find("{") :])
    assert payload["authenticator_is_none"] is True
    assert payload["trading_required"] is False
    assert payload["network_check"] == "ok"
    assert payload["trading_rules"] == 508 or (isinstance(payload["trading_rules"], int) and payload["trading_rules"] > 0)
    btc = payload["btc_meta"]
    assert btc["trading_pair"] == "BTC-USD"
    assert btc["min_notional_size"] == "10"
    assert payload["user_stream_started"] is False
    assert payload["status_polling_started"] is False
    assert payload["start_network"] == "ok"
    assert payload["stop_network"] == "ok"
    assert payload["forbidden_called"] == []
