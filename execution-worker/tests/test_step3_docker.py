"""STEP 3: production Worker image is official hummingbot v2.16.0 + Worker app."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

WORKER_ROOT = Path(__file__).resolve().parents[1]
IMAGE = "newhbot-execution-worker:step3"
BASE = "hummingbot/hummingbot:version-2.16.0"


def _docker() -> str | None:
    found = shutil.which("docker")
    if found:
        return found
    user_install = Path.home() / "AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe"
    if user_install.is_file():
        return str(user_install)
    return None


@pytest.fixture(scope="module")
def docker_bin() -> str:
    docker = _docker()
    if docker is None:
        pytest.skip("STEP 3 Docker not available")
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


def test_step3_worker_image_imports_hummingbot_and_blocks_execution(docker_bin: str, worker_image: str) -> None:
    code = r"""
import json, os, sys
from pathlib import Path
report = {"python": sys.version, "execution_enabled_env": os.environ.get("EXECUTION_ENABLED")}
version = Path("/home/hummingbot/hummingbot/VERSION").read_text().strip()
report["hummingbot_version"] = version
from hummingbot.connector.derivative.hyperliquid_perpetual.hyperliquid_perpetual_derivative import HyperliquidPerpetualDerivative
report["import_ok"] = True
from app.factory import build_runtime
from app.config import WorkerConfig
from app.readonly_guard import ReadOnlyViolation
cfg = WorkerConfig(mode="hyperliquid", execution_enabled=False, trading_pair="BTC-USD")
runtime = build_runtime(cfg)
inner = runtime.inner
report["adapter"] = type(inner).__name__
report["bridge"] = type(inner.connector).__name__
report["guard"] = type(inner.connector.connector).__name__
g = inner.connector.connector
violations = []
for name in ("buy", "sell", "_place_order", "cancel", "set_leverage"):
    try:
        getattr(g, name)()
    except Exception as exc:
        violations.append(type(exc).__name__)
report["guard_exceptions"] = violations
try:
    build_runtime(WorkerConfig(mode="hyperliquid", execution_enabled=True))
    report["enabled_rejected"] = False
except RuntimeError as exc:
    report["enabled_rejected"] = "EXECUTION_ENABLED" in str(exc)
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
    assert payload["hummingbot_version"] == "2.16.0"
    assert payload["import_ok"] is True
    assert payload["adapter"] == "HyperliquidExecutionAdapter"
    assert payload["bridge"] == "ReadOnlyHummingbotBridge"
    assert payload["guard"] == "ReadOnlyGuard"
    assert payload["guard_exceptions"] == ["ReadOnlyViolation"] * 5
    assert payload["enabled_rejected"] is True
    assert payload["execution_enabled_env"] == "false"


def test_step3_worker_http_health_readonly(docker_bin: str, worker_image: str) -> None:
    name = "newhbot-step3-health"
    subprocess.run([docker_bin, "rm", "-f", name], capture_output=True, check=False)
    run = subprocess.run(
        [
            docker_bin,
            "run",
            "-d",
            "--name",
            name,
            "-e",
            "EXECUTION_ENABLED=false",
            "-e",
            "EXECUTION_MODE=hyperliquid",
            worker_image,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    try:
        assert run.returncode == 0, run.stdout + run.stderr
        health = None
        for _ in range(25):
            time.sleep(1)
            inner = subprocess.run(
                [
                    docker_bin,
                    "exec",
                    name,
                    "/opt/conda/envs/hummingbot/bin/python",
                    "-c",
                    "import urllib.request, json; print(urllib.request.urlopen('http://127.0.0.1:8001/health').read().decode())",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            if inner.returncode == 0 and inner.stdout.strip().startswith("{"):
                health = json.loads(inner.stdout)
                break
        assert health is not None, "worker /health did not become ready"
        assert health["execution_enabled"] is False
        assert health["mode"] == "hyperliquid"
        assert health["hummingbot_version"] == "v2.16.0"
    finally:
        subprocess.run([docker_bin, "rm", "-f", name], capture_output=True, check=False)
