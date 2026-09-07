"""STEP 4 Docker: write-loop analysis, Guard dual-lock, optional authenticated read."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

WORKER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = WORKER_ROOT.parent
IMAGE = "newhbot-execution-worker:step4"
BASE = "hummingbot/hummingbot:version-2.16.0"
WRITE_PROBE = WORKER_ROOT / "scripts" / "step4_write_loop_probe.py"
AUTH_PROBE = WORKER_ROOT / "scripts" / "step4_auth_readonly_probe.py"


def _docker() -> str | None:
    found = shutil.which("docker")
    if found:
        return found
    user_install = Path.home() / "AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe"
    if user_install.is_file():
        return str(user_install)
    return None


def _host_credentials() -> tuple[str, str] | None:
    secret = os.environ.get("HYPERLIQUID_PERPETUAL_SECRET_KEY", "").strip()
    address = os.environ.get("HYPERLIQUID_PERPETUAL_ADDRESS", "").strip()
    env_path = REPO_ROOT / ".env"
    if (not secret or not address) and env_path.is_file():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key == "HYPERLIQUID_PERPETUAL_SECRET_KEY" and not secret:
                secret = value
            if key == "HYPERLIQUID_PERPETUAL_ADDRESS" and not address:
                address = value
    if secret and address:
        return secret, address
    return None


@pytest.fixture(scope="module")
def docker_bin() -> str:
    docker = _docker()
    if docker is None:
        pytest.skip("STEP 4 Docker not available")
    inspect = subprocess.run([docker, "image", "inspect", BASE], capture_output=True, text=True, check=False)
    if inspect.returncode != 0:
        pytest.skip(f"base image {BASE} not present")
    return docker


@pytest.fixture(scope="module")
def worker_image(docker_bin: str) -> str:
    result = subprocess.run(
        [docker_bin, "build", "-t", IMAGE, str(WORKER_ROOT)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return IMAGE


def test_step4_start_network_has_lost_order_auto_cancel(docker_bin: str) -> None:
    result = subprocess.run(
        [
            docker_bin,
            "run",
            "--rm",
            "-e",
            "PYTHONPATH=/home/hummingbot",
            "-v",
            f"{WRITE_PROBE.resolve().as_posix()}:/tmp/probe.py:ro",
            "--entrypoint",
            "/opt/conda/envs/hummingbot/bin/python",
            BASE,
            "/tmp/probe.py",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout[result.stdout.find("{") :])
    assert payload["import_ok"] is True
    assert payload["lost_orders_loop_in_start_network"] is True
    assert payload["lost_orders_gated_by_trading_required"] is True
    assert payload["cancel_lost_orders_calls_execute_cancel"] is True
    assert payload["start_network_excerpt_has_write_risk"] is True


def test_step4_worker_without_credentials_stays_public_readonly(docker_bin: str, worker_image: str) -> None:
    code = r"""
import json
from app.factory import build_runtime
from app.config import WorkerConfig
from app.hummingbot_readonly import credentials_supplied
cfg = WorkerConfig(mode="hyperliquid", execution_enabled=False, trading_pair="BTC-USD")
runtime = build_runtime(cfg)
bridge = runtime.inner.connector
report = {
    "credentials_supplied": credentials_supplied(),
    "authenticated": bool(getattr(bridge, "authenticated", False)),
    "account_read": bridge.account_read,
    "guard": type(bridge.connector).__name__,
    "execution_enabled": runtime.config.execution_enabled,
}
print(json.dumps(report))
"""
    result = subprocess.run(
        [
            docker_bin,
            "run",
            "--rm",
            "-e",
            "EXECUTION_ENABLED=false",
            "-e",
            "EXECUTION_MODE=hyperliquid",
            "--entrypoint",
            "/opt/conda/envs/hummingbot/bin/python",
            worker_image,
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout[result.stdout.find("{") :])
    assert payload["credentials_supplied"] is False
    assert payload["authenticated"] is False
    assert payload["account_read"] == "skipped_no_user_address"
    assert payload["guard"] == "ReadOnlyGuard"
    assert payload["execution_enabled"] is False


def test_step4_write_loops_disabled_on_real_connector(docker_bin: str, worker_image: str) -> None:
    code = r"""
import asyncio, json
from app.hummingbot_readonly import disable_exchange_write_loops, instantiate_readonly, try_load_hummingbot_connector_class
from app.readonly_guard import ReadOnlyViolation
cls = try_load_hummingbot_connector_class()
raw = instantiate_readonly(cls, ["BTC-USD"])
disable_exchange_write_loops(raw)

async def main():
    report = {"write_loops_disabled": bool(raw._newhbot_write_loops_disabled)}
    await raw._cancel_lost_orders()
    report["lost_cancel_noop"] = True
    blocked = []
    for name in ("buy", "sell", "cancel", "set_leverage"):
        try:
            getattr(raw, name)()
            blocked.append(name + "=NOT_BLOCKED")
        except ReadOnlyViolation:
            blocked.append(name)
    try:
        await raw._place_order()
        blocked.append("_place_order=NOT_BLOCKED")
    except ReadOnlyViolation:
        blocked.append("_place_order")
    try:
        await raw._execute_order_cancel()
        blocked.append("_execute_order_cancel=NOT_BLOCKED")
    except ReadOnlyViolation:
        blocked.append("_execute_order_cancel")
    report["blocked"] = blocked
    print(json.dumps(report))

asyncio.run(main())
"""
    result = subprocess.run(
        [
            docker_bin,
            "run",
            "--rm",
            "-e",
            "EXECUTION_ENABLED=false",
            "--entrypoint",
            "/opt/conda/envs/hummingbot/bin/python",
            worker_image,
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout[result.stdout.find("{") :])
    assert payload["write_loops_disabled"] is True
    assert payload["lost_cancel_noop"] is True
    assert "buy" in payload["blocked"]
    assert "sell" in payload["blocked"]
    assert "_place_order" in payload["blocked"]
    assert "_execute_order_cancel" in payload["blocked"]
    assert "set_leverage" in payload["blocked"]
    assert all("NOT_BLOCKED" not in item for item in payload["blocked"])


def test_step4_authenticated_readonly_account_or_blocked(docker_bin: str, worker_image: str, tmp_path: Path) -> None:
    creds = _host_credentials()
    if creds is None:
        pytest.skip("BLOCKED: authenticated credential not supplied")
    secret, address = creds
    secret_file = tmp_path / "hyperliquid_perpetual_secret_key"
    address_file = tmp_path / "hyperliquid_perpetual_address"
    secret_file.write_text(secret, encoding="utf-8")
    address_file.write_text(address, encoding="utf-8")
    result = subprocess.run(
        [
            docker_bin,
            "run",
            "--rm",
            "-e",
            "EXECUTION_ENABLED=false",
            "-e",
            "EXECUTION_MODE=hyperliquid",
            "-e",
            "HYPERLIQUID_PERPETUAL_SECRET_KEY_FILE=/run/secrets/hyperliquid_perpetual_secret_key",
            "-e",
            "HYPERLIQUID_PERPETUAL_ADDRESS_FILE=/run/secrets/hyperliquid_perpetual_address",
            "-v",
            f"{secret_file.resolve().as_posix()}:/run/secrets/hyperliquid_perpetual_secret_key:ro",
            "-v",
            f"{address_file.resolve().as_posix()}:/run/secrets/hyperliquid_perpetual_address:ro",
            "-v",
            f"{AUTH_PROBE.resolve().as_posix()}:/tmp/probe.py:ro",
            "--entrypoint",
            "/opt/conda/envs/hummingbot/bin/python",
            worker_image,
            "/tmp/probe.py",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, "authenticated probe failed (no secret in this message)"
    payload = json.loads(result.stdout[result.stdout.find("{") :])
    assert payload["credentials_supplied"] is True
    assert payload["execution_enabled"] is False
    assert payload["authenticated"] is True
    assert payload["write_loops_disabled"] is True
    assert payload["guard_blocks"]["buy"] == "ReadOnlyViolation"
    assert payload["guard_blocks"]["sell"] == "ReadOnlyViolation"
    assert payload["guard_blocks"]["_place_order"] == "ReadOnlyViolation"
    assert payload["guard_blocks"]["cancel"] == "ReadOnlyViolation"
    assert payload["guard_blocks"]["set_leverage"] == "ReadOnlyViolation"
    assert payload["place_blocked"] is True
    assert payload["cancel_blocked"] is True
    assert payload["leverage_blocked"] is True
    assert payload["account_connection"] in {"VERIFIED", "NOT VERIFIED", "BLOCKED"}
    dumped = json.dumps(payload)
    assert secret not in dumped
    assert address not in dumped
