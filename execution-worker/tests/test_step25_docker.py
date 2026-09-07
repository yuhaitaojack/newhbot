"""STEP 2.5 official hummingbot/hummingbot:version-2.16.0 runtime probes.

Skipped when Docker or the image is absent. Never mixed with FakeConnector as HB.
Never sends real orders. Never supplies API keys.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WORKER_ROOT = Path(__file__).resolve().parents[1]
IMAGE = "hummingbot/hummingbot:version-2.16.0"
INVENTORY = WORKER_ROOT / "scripts" / "step25_inventory_probe.py"
READONLY_RUNTIME = WORKER_ROOT / "scripts" / "step25_readonly_runtime_probe.py"
UNAUTH_START = WORKER_ROOT / "scripts" / "step25_unauth_start_network_probe.py"
CLOID_STUB = WORKER_ROOT / "scripts" / "step25_cloid_stub_probe.py"


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
        [docker, "image inspect", IMAGE] if False else [docker, "image", "inspect", IMAGE],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _run_in_hummingbot(
    docker: str,
    script: Path,
    *,
    timeout: int = 60,
    extra_volumes: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        docker,
        "run",
        "--rm",
        "-e",
        "PYTHONPATH=/home/hummingbot:/tmp/worker",
        "-w",
        "/home/hummingbot",
        "-v",
        f"{script.resolve().as_posix()}:/tmp/probe.py:ro",
        "-v",
        f"{(WORKER_ROOT / 'app').resolve().as_posix()}:/tmp/worker/app:ro",
    ]
    if extra_volumes:
        cmd.extend(extra_volumes)
    cmd.extend(
        [
            "--entrypoint",
            "/opt/conda/envs/hummingbot/bin/python",
            IMAGE,
            "/tmp/probe.py",
        ]
    )
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)


def _payload(result: subprocess.CompletedProcess[str]) -> dict:
    text = result.stdout
    start = text.find("{")
    assert start >= 0, result.stdout + result.stderr
    return json.loads(text[start:])


@pytest.fixture(scope="module")
def docker_bin() -> str:
    docker = _docker()
    if docker is None:
        pytest.skip("STEP 2.5 Docker not available")
    if not _image_present(docker):
        pytest.skip(f"STEP 2.5 image {IMAGE} not present")
    return docker


def test_step25_inventory_import_instantiate_events(docker_bin: str) -> None:
    result = _run_in_hummingbot(docker_bin, INVENTORY)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = _payload(result)
    assert payload["hummingbot_version_file"] == "2.16.0"
    assert payload["imports"]["HyperliquidPerpetualDerivative"] is True
    assert payload["imports"]["ExchangePyBase"] is True
    assert payload["imports"]["ClientOrderTracker"] is True
    assert payload["imports"]["PerpetualTrading"] is True
    assert payload["instantiate_ok"] is True
    assert payload["trading_required"] is False
    assert payload["authenticator_is_none"] is True
    assert payload["oneway_present"] is True
    assert payload["hedge_present"] is False
    assert payload["has_order_filled"] is True
    assert payload["has_order_cancelled"] is True
    assert payload["has_order_failure"] is True
    assert payload["add_listener_present"] is True
    assert payload["place_source_has_cloid_order_id"] is True
    assert payload["place_source_mentions_retry"] is False
    assert payload["place_source_mentions_renew"] is False
    assert payload["buy_mints_new_client_order_id"] is True
    assert payload["sell_mints_new_client_order_id"] is True
    assert payload["account_positions_len"] == 0
    assert payload["in_flight_orders_len"] == 0


def test_step25_readonly_public_rules_and_quantize(docker_bin: str) -> None:
    result = _run_in_hummingbot(docker_bin, READONLY_RUNTIME, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = _payload(result)
    if payload["network_check"] != "ok":
        pytest.skip(f"public Hyperliquid metadata unavailable: {payload['network_check']}")
    assert payload["authenticator_is_none"] is True
    assert payload["trading_required"] is False
    assert isinstance(payload["trading_rules"], int) and payload["trading_rules"] > 0
    assert payload["btc_meta"]["trading_pair"] == "BTC-USD"
    assert payload["btc_meta"]["min_notional_size"] == "10"
    assert payload["quantize_order_price"] not in (None, "")
    assert payload["quantize_order_amount"] not in (None, "")
    assert payload["user_stream_started"] is False
    assert payload["status_polling_started"] is False
    assert payload["start_network_readonly"] == "ok"
    assert payload["account_positions"] == []
    assert payload["in_flight_orders"] == []


def test_step25_unauth_trading_required_does_not_use_fake_keys(docker_bin: str) -> None:
    result = _run_in_hummingbot(docker_bin, UNAUTH_START, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = _payload(result)
    # Either constructor/start stops without credentials, or authenticator is None
    # and account paths are not started. Never a PASS via fake keys.
    if payload.get("blocked_reason") == "requires authenticated Hyperliquid runtime":
        assert payload.get("constructor") != "used_fake_key"
        return
    assert payload.get("authenticator_is_none") is True
    assert payload.get("user_stream_started") in (False, None)


def test_step25_cloid_injected_on_real_place_order_stub_transport(docker_bin: str) -> None:
    result = _run_in_hummingbot(docker_bin, CLOID_STUB, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = _payload(result)
    assert payload.get("error") is None, payload
    assert payload["adapter_helper_imported"] is True
    assert payload["buy_calls"] == 0
    assert payload["sell_calls"] == 0
    assert payload["api_post_calls"] == 1
    assert payload["wire_cloid"] == payload["order_id_arg"]
    assert payload["wire_cloid"] == "0x" + "ab" * 16
    assert payload["second_cloid"] is False
    assert payload["helper_has_no_inner_retry"] is True
