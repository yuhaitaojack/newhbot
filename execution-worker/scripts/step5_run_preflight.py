"""Host runner for STEP 5 PRE-FLIGHT. Query-only. Never prints secrets."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKER = REPO / "execution-worker"
IMAGE = "newhbot-execution-worker:step5-preflight"
FALLBACK_IMAGE = "newhbot-execution-worker:step4"
PROBE = WORKER / "scripts" / "step5_preflight_probe.py"
APP_DIR = WORKER / "app"


def _docker() -> str | None:
    found = shutil.which("docker")
    if found:
        return found
    user_install = Path.home() / "AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe"
    if user_install.is_file():
        return str(user_install)
    return None


def _local_unresolved() -> dict:
    """SQLite leftover UNKNOWN / reservation. Not exchange truth."""
    db = REPO / "data" / "newhbot.db"
    out = {
        "sqlite_present": db.is_file(),
        "unresolved_order_count": None,
        "reservation_held": None,
    }
    if not db.is_file():
        return out
    import sqlite3

    con = sqlite3.connect(str(db))
    try:
        unresolved = con.execute(
            "SELECT COUNT(*) FROM orders WHERE status IN "
            "('PENDING_SUBMISSION','SUBMITTING','ACK','OPEN','PARTIAL','UNKNOWN')"
        ).fetchone()[0]
        held = con.execute("SELECT order_id FROM open_reservations WHERE id = 1").fetchone()
        out["unresolved_order_count"] = int(unresolved)
        out["reservation_held"] = bool(held and held[0])
    except sqlite3.Error as exc:
        out["sqlite_error"] = type(exc).__name__
    finally:
        con.close()
    return out


def _host_credentials() -> tuple[str, str] | None:
    secret = os.environ.get("HYPERLIQUID_PERPETUAL_SECRET_KEY", "").strip()
    address = os.environ.get("HYPERLIQUID_PERPETUAL_ADDRESS", "").strip()
    env_path = REPO / ".env"
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


def main() -> int:
    probe = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else PROBE
    docker = _docker()
    if docker is None:
        print(json.dumps({"error": "docker_unavailable"}))
        return 2
    creds = _host_credentials()
    if creds is None:
        print(json.dumps({"error": "credentials_missing"}))
        return 2
    secret, address = creds
    build = subprocess.run(
        [docker, "build", "-t", IMAGE, str(WORKER)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    image = IMAGE
    app_bind_mounted = False
    registry_build = build.returncode == 0
    if not registry_build:
        inspect = subprocess.run(
            [docker, "image", "inspect", FALLBACK_IMAGE],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspect.returncode != 0:
            print(json.dumps({"error": "docker_build_failed", "fallback_missing": True}))
            return 2
        image = FALLBACK_IMAGE
        app_bind_mounted = True
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        secret_file = tmp_path / "secret"
        address_file = tmp_path / "address"
        secret_file.write_text(secret, encoding="utf-8")
        address_file.write_text(address, encoding="utf-8")
        command = [
            docker,
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
            f"{probe.as_posix()}:/tmp/probe.py:ro",
        ]
        if app_bind_mounted:
            command.extend(["-v", f"{APP_DIR.resolve().as_posix()}:/app/app:ro"])
        command.extend(
            [
                "--entrypoint",
                "/opt/conda/envs/hummingbot/bin/python",
                image,
                "/tmp/probe.py",
            ]
        )
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=240,
        )
    if result.returncode != 0:
        err = (result.stderr or "")[-800:]
        err = err.replace(secret, "[redacted]").replace(address, "[redacted]")
        print(json.dumps({"error": "probe_failed", "exit": result.returncode, "stderr_tail": err}))
        return 2
    text = result.stdout
    start = text.find("{")
    payload = json.loads(text[start:])
    payload["image"] = image
    payload["registry_build"] = registry_build
    payload["current_app_bind_mounted"] = app_bind_mounted
    payload["local_sqlite"] = _local_unresolved()
    dumped = json.dumps(payload)
    if secret in dumped or address in dumped:
        print(json.dumps({"error": "probe_leaked_credentials"}))
        return 2
    print(dumped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
