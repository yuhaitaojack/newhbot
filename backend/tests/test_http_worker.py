from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from app.core.config import Settings
from app.core.enums import PositionSide
from app.execution.client import HttpExecutionClient
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_ROOT = REPO_ROOT / "execution-worker"


class CountingHttpExecutionClient(HttpExecutionClient):
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        super().__init__(base_url, timeout=timeout)
        self.place_calls = 0

    async def place_order(self, request):
        self.place_calls += 1
        return await super().place_order(request)


def test_settings_configure_worker_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_WORKER_READ_TIMEOUT_SECONDS", "12.5")

    settings = Settings()

    assert settings.execution_worker_read_timeout_seconds == 12.5


@pytest.mark.asyncio
async def test_http_worker_retries_transient_candle_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("GET", "http://worker/rpc/candles")
    responses = [
        httpx.Response(500, request=request),
        httpx.Response(200, json=[{"timestamp": 1}], request=request),
    ]

    class _FakeReadClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            return responses.pop(0)

    execution = HttpExecutionClient("http://worker")
    monkeypatch.setattr(execution, "_read_client", lambda: _FakeReadClient())

    assert await execution.get_candles("BTC-USD", "5m", 200) == [{"timestamp": 1}]
    assert responses == []


@pytest.mark.asyncio
async def test_http_worker_retries_transient_balance_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("GET", "http://worker/rpc/balance")
    responses = [
        httpx.Response(500, request=request),
        httpx.Response(200, json={"equity": "1000", "available": "900", "margin_used": "100"}, request=request),
    ]

    class _FakeReadClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            return responses.pop(0)

    execution = HttpExecutionClient("http://worker")
    monkeypatch.setattr(execution, "_read_client", lambda: _FakeReadClient())

    balance = await execution.get_balance()
    assert balance.available == Decimal("900")
    assert responses == []


@pytest.mark.asyncio
async def test_http_worker_retries_transient_position_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("GET", "http://worker/rpc/position")
    responses = [
        httpx.Response(503, request=request),
        httpx.Response(
            200,
            json={
                "symbol": "BTC-USD",
                "side": "FLAT",
                "size": "0",
                "entry_price": None,
                "unrealized_pnl": "0",
            },
            request=request,
        ),
    ]

    class _FakeReadClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            return responses.pop(0)

    execution = HttpExecutionClient("http://worker")
    monkeypatch.setattr(execution, "_read_client", lambda: _FakeReadClient())

    position = await execution.get_position("BTC-USD")
    assert position.side == PositionSide.FLAT
    assert responses == []


@pytest.mark.asyncio
async def test_http_worker_retries_transient_configure_403(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "http://worker/rpc/configure")
    responses = [httpx.Response(403, request=request), httpx.Response(200, json={"ok": True}, request=request)]

    class _FakeWriteClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            return responses.pop(0)

    execution = HttpExecutionClient("http://worker")
    monkeypatch.setattr(execution, "_client", lambda: _FakeWriteClient())

    await execution.configure("BTC-USD", Decimal("0.01"), 1)
    assert responses == []


class _DelayedReadHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            payload = {
                "ready": True,
                "worker_state": "READY",
                "mode": "mock",
                "execution_enabled": False,
                "sync_status": "SYNCED",
            }
        elif path == "/rpc/position":
            time.sleep(self.server.response_delay)  # type: ignore[attr-defined]
            payload = {
                "symbol": "BTC-USD",
                "side": "FLAT",
                "size": "0",
                "entry_price": None,
                "unrealized_pnl": "0",
            }
        elif path == "/rpc/balance":
            payload = {"equity": "1000", "available": "1000", "margin_used": "0"}
        else:
            self.send_error(404)
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


@contextmanager
def _delayed_read_worker(delay_seconds: float):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DelayedReadHandler)
    server.response_delay = delay_seconds  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_configured_read_timeout_allows_slow_status_query(tmp_path) -> None:
    with _delayed_read_worker(2.2) as url:
        settings = Settings(
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'slow-read.db').as_posix()}",
            execution_worker_url=url,
            execution_worker_read_timeout_seconds=3.5,
            execution_mode="mock",
            cors_origins="http://test",
            strategies_dir=str(tmp_path / "strategy-versions"),
        )
        app = create_app(settings=settings, bootstrap_schema=True)
        started = time.monotonic()
        with TestClient(app) as client:
            status = client.get("/api/status")
        elapsed = time.monotonic() - started

    assert status.status_code == 200
    assert status.json()["system_state"] == "STOPPED"
    assert status.json()["position"]["side"] == PositionSide.FLAT.value
    assert elapsed >= 2.0


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _wait_health(url: str, proc: subprocess.Popen, log_path: Path, *, attempts: int = 80) -> None:
    last: Exception | None = None
    for _ in range(attempts):
        if proc.poll() is not None:
            logs = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            raise RuntimeError(f"worker exited {proc.returncode} before healthy: {logs}")
        try:
            response = httpx.get(f"{url}/health", timeout=1.0, trust_env=False)
            if response.status_code == 200:
                return
            last = RuntimeError(f"status {response.status_code}")
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(0.1)
    logs = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    raise RuntimeError(f"worker did not become healthy at {url}: {last}\n{logs}")


def _start_worker(port: int, log_path: Path | None = None) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(WORKER_ROOT)
    log_path = log_path or Path(os.environ.get("TEMP", ".")) / f"newhbot-worker-{port}.log"
    log_file = log_path.open("w", encoding="utf-8")
    kwargs: dict = {
        "cwd": str(WORKER_ROOT),
        "env": env,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        **kwargs,
    )
    proc._log_file = log_file  # type: ignore[attr-defined]
    proc._log_path = log_path  # type: ignore[attr-defined]
    try:
        _wait_health(f"http://127.0.0.1:{port}", proc, log_path)
    except Exception:
        _stop_worker(proc)
        raise
    return proc


def _stop_worker(proc: subprocess.Popen) -> None:
    log_file = getattr(proc, "_log_file", None)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    if log_file is not None:
        log_file.close()


@pytest.fixture
def worker_proc(tmp_path):
    port = _free_port()
    proc = _start_worker(port, log_path=tmp_path / "worker.log")
    url = f"http://127.0.0.1:{port}"
    try:
        yield url, proc, port
    finally:
        _stop_worker(proc)


def test_http_worker_flat_long_reject_close_and_unknown(tmp_path, worker_proc) -> None:
    url, proc, port = worker_proc
    execution = CountingHttpExecutionClient(url)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'http.db').as_posix()}",
        execution_worker_url=url,
        execution_mode="mock",
        cors_origins="http://test",
    )
    app = create_app(settings=settings, execution=execution, bootstrap_schema=True)
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["worker_ok"] is True

        start = client.post("/api/trading/start")
        assert start.json()["ok"] is True

        opened = client.post("/api/trading/signal", json={"signal": "LONG"})
        assert opened.status_code == 200
        assert opened.json()["accepted"] is True
        assert execution.place_calls == 1
        assert client.get("/api/positions").json()[0]["side"] == PositionSide.LONG.value
        worker_pos = httpx.get(
            f"{url}/rpc/position", params={"symbol": "BTC-USD"}, timeout=5, trust_env=False
        )
        assert worker_pos.json()["side"] == PositionSide.LONG.value

        second = client.post("/api/trading/signal", json={"signal": "LONG"})
        assert second.json()["accepted"] is False
        reverse = client.post("/api/trading/signal", json={"signal": "SHORT"})
        assert reverse.json()["accepted"] is False
        assert "reverse" in reverse.json()["reason"]
        assert execution.place_calls == 1

        closed = client.post("/api/trading/signal", json={"signal": "CLOSE"})
        assert closed.json()["ok"] is True
        assert client.get("/api/positions").json()[0]["side"] == PositionSide.FLAT.value
        assert execution.place_calls == 2

        httpx.post(
            f"{url}/rpc/test/behavior",
            json={"behavior": "network_before_accept"},
            timeout=5,
            trust_env=False,
        )
        httpx.post(f"{url}/rpc/test/query_fail", json={"enabled": True}, timeout=5, trust_env=False)
        unknown = client.post("/api/trading/signal", json={"signal": "LONG"})
        unknown_body = unknown.json()
        assert unknown_body.get("status") == "UNKNOWN"
        assert unknown_body.get("accepted") is False
        assert client.get("/api/status").json()["system_state"] == "RECOVERY"
        httpx.post(f"{url}/rpc/test/query_fail", json={"enabled": False}, timeout=5, trust_env=False)
        httpx.post(f"{url}/rpc/test/behavior", json={"behavior": "fill"}, timeout=5, trust_env=False)
        blocked = client.post("/api/trading/signal", json={"signal": "LONG"})
        assert blocked.json()["accepted"] is False
        place_after_unknown = execution.place_calls

        _stop_worker(proc)
        down = client.get("/api/health")
        assert down.json()["worker_ok"] is False
        restarted = _start_worker(port)
        try:
            after_restart = client.post("/api/trading/signal", json={"signal": "LONG"})
            assert after_restart.json()["accepted"] is False
            assert execution.place_calls == place_after_unknown
        finally:
            _stop_worker(restarted)
