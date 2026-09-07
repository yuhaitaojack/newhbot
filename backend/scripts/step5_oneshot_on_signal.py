"""Wait for a real ema5break LONG/SHORT, then run a testnet one-shot via TradingController.

Requires an explicit per-run testnet confirmation; never targets mainnet.
Does not start a continuous strategy loop. Does not print secrets.
Does not change Compose / Dockerfile defaults.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from decimal import Decimal
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
WORKER = REPO / "execution-worker"
STRATEGY = REPO / "strategies" / "ema5break" / "strategy.py"
IMAGE = "newhbot-execution-worker:step4"
CONTAINER = "newhbot-step5-oneshot-worker"
WORKER_URL = "http://127.0.0.1:8001"
BACKEND_URL = "http://127.0.0.1:8000"
TARGET_NOTIONAL = Decimal("10.5")
MAX_NOTIONAL = Decimal("12")
STATE_PATH = REPO / "data" / "step5_oneshot_state.json"
REPORT_PATH = REPO / "docs" / "STEP_5_MAINNET_ONE_SHOT_REPORT.md"
WORKER_START_LOG = REPO / "data" / "step5_oneshot_worker_start.log"
BACKEND_LOG = REPO / "data" / "step5_oneshot_backend.log"
TESTNET_DOMAIN = "hyperliquid_perpetual_testnet"
TESTNET_INFO_URL = "https://api.hyperliquid-testnet.xyz/info"
TESTNET_CONFIRMATION = "I_CONFIRM_TESTNET_ONE_SHOT"
_SECRET_TMP_DIR: Path | None = None


def _require_testnet_confirmation() -> None:
    domain = os.environ.get("HYPERLIQUID_DOMAIN", TESTNET_DOMAIN).strip()
    confirmation = os.environ.get("STEP5_CONFIRMATION", "").strip()
    if domain != TESTNET_DOMAIN:
        raise RuntimeError("testnet_only")
    if confirmation != TESTNET_CONFIRMATION:
        raise RuntimeError("explicit_testnet_confirmation_required")


def _load_strategy():
    import importlib.util

    spec = importlib.util.spec_from_file_location("ema5break", STRATEGY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _candles() -> list[dict]:
    end = int(time.time() * 1000)
    start = end - 5 * 60 * 1000 * 40
    body = json.dumps(
        {"type": "candleSnapshot", "req": {"coin": "BTC", "interval": "5m", "startTime": start, "endTime": end}}
    ).encode()
    req = urllib.request.Request(TESTNET_INFO_URL, data=body, headers={"Content-Type": "application/json"})
    raw = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if not isinstance(raw, list):
        raise RuntimeError("unexpected candle payload")
    now = int(time.time() * 1000)
    closed = [item for item in raw if int(item.get("T") or 0) < now]
    bars = []
    for item in closed:
        bars.append(
            {
                "open": float(item["o"]),
                "high": float(item["h"]),
                "low": float(item["l"]),
                "close": float(item["c"]),
                "t": int(item["t"]),
            }
        )
    return bars


def _eval(mod, bars: list[dict]) -> str:
    payload = [{"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]} for b in bars]
    return str(mod.on_bar({"bars": payload, "position_side": "FLAT", "symbol": "BTC-USD", "interval": "5m"}))


def _wait_signal() -> dict:
    mod = _load_strategy()
    last_t = None
    while True:
        try:
            bars = _candles()
        except Exception as exc:
            print(f"WATCH_CANDLE_ERROR {type(exc).__name__}", flush=True)
            time.sleep(20)
            continue
        if len(bars) < 20:
            print("WATCH_HOLD too_few_bars", flush=True)
            time.sleep(20)
            continue
        t = bars[-1]["t"]
        sig = _eval(mod, bars)
        if t != last_t:
            last = bars[-1]
            print(
                f"WATCH {sig} closed_t={t} o={last['open']} h={last['high']} l={last['low']} c={last['close']}",
                flush=True,
            )
            last_t = t
        if sig in {"LONG", "SHORT"}:
            prev = bars[-2] if len(bars) > 1 else None
            payload = {
                "event": "SIGNAL_READY",
                "signal": sig,
                "closed_t": t,
                "last_bar": bars[-1],
                "prev_bar": prev,
            }
            print(json.dumps(payload), flush=True)
            return payload
        time.sleep(20)


def _creds() -> tuple[str, str]:
    env_path = REPO / ".env"
    secret = os.environ.get("HYPERLIQUID_PERPETUAL_SECRET_KEY", "").strip()
    address = os.environ.get("HYPERLIQUID_PERPETUAL_ADDRESS", "").strip()
    if env_path.is_file():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key == "HYPERLIQUID_PERPETUAL_SECRET_KEY" and not secret:
                secret = value
            if key == "HYPERLIQUID_PERPETUAL_ADDRESS" and not address:
                address = value
    if not secret or not address:
        raise RuntimeError("credentials_missing")
    return secret, address


def _docker() -> str:
    found = shutil.which("docker")
    if found:
        return found
    raise RuntimeError("docker_unavailable")


def _start_worker(secret: str, address: str) -> None:
    global _SECRET_TMP_DIR
    docker = _docker()
    subprocess.run([docker, "rm", "-f", CONTAINER], check=False, capture_output=True)
    tmp = Path(tempfile.mkdtemp(prefix="step5-oneshot-"))
    _SECRET_TMP_DIR = tmp
    (tmp / "secret").write_text(secret, encoding="utf-8")
    (tmp / "address").write_text(address, encoding="utf-8")
    cmd = [
        docker,
        "run",
        "-d",
        "--name",
        CONTAINER,
        "-p",
        "127.0.0.1:8001:8001",
        "-e",
        "EXECUTION_ENABLED=true",
        "-e",
        "EXECUTION_MODE=hyperliquid",
        "-e",
        f"HYPERLIQUID_DOMAIN={TESTNET_DOMAIN}",
        "-e",
        "EXECUTION_TRADING_PAIR=BTC-USD",
        "-e",
        "HYPERLIQUID_PERPETUAL_SECRET_KEY_FILE=/run/secrets/hyperliquid_perpetual_secret_key",
        "-e",
        "HYPERLIQUID_PERPETUAL_ADDRESS_FILE=/run/secrets/hyperliquid_perpetual_address",
        "-v",
        f"{(tmp / 'secret').resolve().as_posix()}:/run/secrets/hyperliquid_perpetual_secret_key:ro",
        "-v",
        f"{(tmp / 'address').resolve().as_posix()}:/run/secrets/hyperliquid_perpetual_address:ro",
        "-v",
        f"{(WORKER / 'app').resolve().as_posix()}:/app/app:ro",
        "--entrypoint",
        "/opt/conda/envs/hummingbot/bin/python",
        IMAGE,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8001",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    WORKER_START_LOG.parent.mkdir(parents=True, exist_ok=True)
    WORKER_START_LOG.write_text(
        f"returncode={result.returncode}\nstdout_len={len(result.stdout or '')}\nstderr_type={type(result.stderr).__name__}\n",
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError("worker_start_failed")


def _stop_worker() -> None:
    subprocess.run([_docker(), "rm", "-f", CONTAINER], check=False, capture_output=True)


def _wait_http(url: str, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=5.0, trust_env=False) as client:
                if client.get(url).status_code == 200:
                    return
        except httpx.HTTPError:
            time.sleep(1)
    raise RuntimeError(f"timeout waiting {url}")


def _get_json(client: httpx.Client, url: str) -> dict | list | None:
    try:
        response = client.get(url)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return {"http_status": response.status_code, "error": response.text[:300]}
    try:
        return response.json()
    except ValueError:
        return None


def _wait_worker_reachable(timeout: float = 90.0) -> dict:
    """Wait for the live worker HTTP process; Backend performs connect/READY next."""
    deadline = time.time() + timeout
    last: dict = {}
    with httpx.Client(timeout=10.0, trust_env=False) as client:
        while time.time() < deadline:
            payload = _get_json(client, f"{WORKER_URL}/health")
            if isinstance(payload, dict):
                last = payload
                enabled = bool(payload.get("execution_enabled"))
                if enabled:
                    return payload
            time.sleep(2)
    return last


def _is_unknown(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return str(payload.get("status")) == "UNKNOWN" or "UNKNOWN" in str(payload.get("reason") or "")


def _order_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _fill_for(fills: list[dict], cloid: str | None) -> dict | None:
    if not cloid:
        return None
    matched = [item for item in fills if str(item.get("cloid")) == str(cloid)]
    return matched[-1] if matched else None


def _write_report(payload: dict) -> None:
    result = str(payload.get("STEP_5_RESULT") or "STOPPED")
    orders = _order_rows(payload.get("orders"))
    fills = _order_rows(payload.get("fills"))
    opened = payload.get("open") if isinstance(payload.get("open"), dict) else {}
    closed = payload.get("close") if isinstance(payload.get("close"), dict) else {}
    open_cloid = opened.get("cloid")
    close_cloid = closed.get("cloid")
    open_fill = _fill_for(fills, open_cloid)
    close_fill = _fill_for(fills, close_cloid)
    open_order = next((item for item in orders if str(item.get("cloid")) == str(open_cloid)), None) if open_cloid else None
    close_order = next((item for item in orders if str(item.get("cloid")) == str(close_cloid)), None) if close_cloid else None
    worker_after = payload.get("worker_health_after") if isinstance(payload.get("worker_health_after"), dict) else {}
    final_pos = payload.get("final_position") if isinstance(payload.get("final_position"), dict) else {}
    final_bal = payload.get("final_balance") if isinstance(payload.get("final_balance"), dict) else {}
    signal_meta = payload.get("signal_meta") if isinstance(payload.get("signal_meta"), dict) else {}
    submitted = len(orders)
    md = f"""# STEP 5 — TESTNET ONE-SHOT REPORT

**日期：** 2026-09-03  
**状态：已停止。** 这是一次性 testnet 测试，不进入 STEP 6。

**STEP_5_RESULT = {result}**

Compose / Dockerfile / `.env.example` 默认 `EXECUTION_ENABLED` 未改为 true。运行时武装仅用于本容器，结束后已 `docker rm`。

---

## 信号

| 项 | 值 |
| --- | --- |
| 实际信号 | {payload.get("signal")} |
| strategy | ema5break |
| pair | BTC-USD |
| interval | 5m |
| signal candle timestamp | {signal_meta.get("closed_t")} |
| last bar | {json.dumps(signal_meta.get("last_bar"), default=str)} |
| prev bar | {json.dumps(signal_meta.get("prev_bar"), default=str)} |
| 伪造信号 | 否 |

---

## OPEN

| 项 | 值 |
| --- | --- |
| OPEN cloid | {open_cloid} |
| OPEN order ID | {(open_order or {}).get("exchange_oid")} |
| OPEN 状态 | {opened.get("status") or opened.get("reason")} |
| OPEN 实际成交数量 | {(open_fill or {}).get("quantity")} |
| OPEN 实际成交价格 | {(open_fill or {}).get("price")} |
| accepted | {opened.get("accepted")} |

---

## CLOSE

| 项 | 值 |
| --- | --- |
| CLOSE cloid | {close_cloid} |
| CLOSE order ID | {(close_order or {}).get("exchange_oid")} |
| CLOSE 状态 | {closed.get("status") or closed.get("reason")} |
| CLOSE 实际成交数量 | {(close_fill or {}).get("quantity")} |
| CLOSE 实际成交价格 | {(close_fill or {}).get("price")} |

---

## 最终交易所状态

| 项 | 值 |
| --- | --- |
| 最终 BTC-USD position | {final_pos.get("side")} size={final_pos.get("size")} |
| 最终账户余额 equity | {final_bal.get("equity")} |
| 最终账户余额 available | {final_bal.get("available")} |
| real orders submitted | {submitted} |
| UNKNOWN 是否发生 | {payload.get("unknown")} |
| Recovery 是否发生 | {payload.get("recovery")} |
| foreign position 是否发生 | {payload.get("foreign_seen")} |
| execution_enabled 最终状态 | {worker_after.get("execution_enabled", "worker_stopped")} |
| bridge_armed 最终状态 | {payload.get("bridge_armed_final", False)} |
| stop_reason | {payload.get("stop_reason")} |

---

## 路径与禁止项

- 下单路径：ema5break → TradingController → HttpExecutionClient → Worker → Adapter → armed Bridge → Hummingbot v2.16.0 → Hyperliquid
- buy/sell/cancel/set_leverage/直接 HTTP 下单：**未作为本脚本路径**
- 自动反手：否
- 默认 Compose/Dockerfile EXECUTION_ENABLED：false

```json
{json.dumps(payload, indent=2, default=str)}
```
"""
    REPORT_PATH.write_text(md, encoding="utf-8")
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _preflight_ok(health: dict, position: dict, positions, precheck: dict, balance: dict, system_state: str | None) -> tuple[bool, str]:
    if not bool(health.get("execution_enabled")):
        return False, "execution_not_armed"
    if health.get("worker_state") != "READY":
        return False, "worker_not_ready"
    if health.get("recovery_reason") not in {None, "null"}:
        return False, "worker_recovery"
    if system_state != "RUNNING":
        return False, "system_not_running"
    if str(position.get("side")) != "FLAT":
        return False, "btc_not_flat"
    foreign = health.get("foreign_symbols") or []
    if foreign:
        return False, "foreign_positions"
    if isinstance(positions, list):
        extra = [
            item
            for item in positions
            if isinstance(item, dict)
            and str(item.get("side")) not in {"FLAT", "None"}
            and str(item.get("symbol")) != "BTC-USD"
            and str(item.get("size") or "0") not in {"0", "0.0", "0E-8"}
        ]
        if extra:
            return False, "foreign_positions"
    if not isinstance(precheck, dict) or precheck.get("status") != "VERIFIED":
        return False, "open_orders_not_verified"
    if precheck.get("configured_open_count") != 0 or precheck.get("other_open_count") != 0:
        return False, "open_orders_not_zero"
    try:
        available = Decimal(str(balance.get("available", "0")))
    except Exception:
        return False, "balance_unreadable"
    if available < 10:
        return False, "funds_insufficient"
    return True, "ok"


def _query_live(worker: httpx.Client, api: httpx.Client | None = None) -> dict:
    health = _get_json(worker, f"{WORKER_URL}/health") or {}
    position = _get_json(worker, f"{WORKER_URL}/rpc/position?symbol=BTC-USD") or {}
    positions = _get_json(worker, f"{WORKER_URL}/rpc/positions") or []
    precheck = _get_json(worker, f"{WORKER_URL}/rpc/open_order_precheck") or {}
    balance = _get_json(worker, f"{WORKER_URL}/rpc/balance") or {}
    status = _get_json(api, f"{BACKEND_URL}/api/status") if api is not None else None
    return {
        "health": health if isinstance(health, dict) else {},
        "position": position if isinstance(position, dict) else {},
        "positions": positions,
        "precheck": precheck if isinstance(precheck, dict) else {},
        "balance": balance if isinstance(balance, dict) else {},
        "status": status if isinstance(status, dict) else {},
    }


def _execute(signal_meta: dict) -> int:
    _require_testnet_confirmation()
    signal = str(signal_meta["signal"])
    secret, address = _creds()
    report: dict = {
        "strategy": "ema5break",
        "signal": signal,
        "signal_meta": signal_meta,
        "pair": "BTC-USD",
        "execution_enabled_compose_default": False,
        "buy_sell_called": False,
        "cancel_called": False,
        "set_leverage_called": False,
        "unknown": False,
        "recovery": False,
        "foreign_seen": False,
        "duplicate_orders": False,
        "auto_reverse": False,
        "bridge_armed_final": False,
        "STEP_5_RESULT": "STOPPED",
    }
    backend_proc = None
    try:
        _start_worker(secret, address)
        _wait_http(f"{WORKER_URL}/health", 90)
        health = _wait_worker_reachable(90)
        report["worker_health_before_start"] = {
            "execution_enabled": health.get("execution_enabled"),
            "worker_state": health.get("worker_state"),
            "recovery_reason": health.get("recovery_reason"),
        }
        db = (REPO / "data" / "step5_oneshot.db").resolve().as_posix()
        env = os.environ.copy()
        env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
        env["EXECUTION_WORKER_URL"] = WORKER_URL
        env["EXECUTION_MODE"] = "mock"
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(BACKEND),
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        BACKEND_LOG.parent.mkdir(parents=True, exist_ok=True)
        log_handle = BACKEND_LOG.open("w", encoding="utf-8")
        backend_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(BACKEND),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        _wait_http(f"{BACKEND_URL}/api/health", 60)
        with httpx.Client(timeout=90.0, trust_env=False) as worker, httpx.Client(timeout=90.0, trust_env=False) as api:
            started = api.post(f"{BACKEND_URL}/api/trading/start").json()
            report["start"] = started
            if not started.get("ok"):
                report["stop_reason"] = "start_failed"
                report["recovery"] = True
                report["STEP_5_RESULT"] = "STOPPED"
                _write_report(report)
                print("STEP5_ONESHOT_DONE start_failed", flush=True)
                return 2
            live = _query_live(worker, api)
            status = live["status"]
            report["preflight"] = {
                "authenticated_worker_state": live["health"].get("worker_state"),
                "execution_enabled": live["health"].get("execution_enabled"),
                "recovery_reason": live["health"].get("recovery_reason"),
                "btc_side": live["position"].get("side"),
                "foreign": live["health"].get("foreign_symbols"),
                "open_order_precheck": live["precheck"],
                "available": str(live["balance"].get("available")),
                "system_state": status.get("system_state"),
            }
            report["foreign_seen"] = bool(live["health"].get("foreign_symbols"))
            ok, reason = _preflight_ok(
                live["health"],
                live["position"],
                live["positions"],
                live["precheck"],
                live["balance"],
                status.get("system_state"),
            )
            if status.get("system_state") == "RECOVERY":
                report["recovery"] = True
            if not ok:
                report["stop_reason"] = f"preflight_failed:{reason}"
                report["STEP_5_RESULT"] = "STOPPED"
                _write_report(report)
                print(f"STEP5_ONESHOT_DONE preflight_failed {reason}", flush=True)
                return 2
            available = Decimal(str(live["balance"].get("available", "0")))
            equity = Decimal(str(live["balance"].get("equity", available)))
            notional = min(TARGET_NOTIONAL, MAX_NOTIONAL)
            pct = (notional / equity * Decimal("100")).quantize(Decimal("0.01"))
            if pct > 90:
                pct = Decimal("90")
            api.put(
                f"{BACKEND_URL}/api/settings",
                json={"trading_pair": "BTC-USD", "leverage": 3, "position_percentage": str(pct)},
            )
            opened = api.post(f"{BACKEND_URL}/api/trading/signal", json={"signal": signal}).json()
            report["open"] = opened
            if _is_unknown(opened):
                report["unknown"] = True
            live_pos = None
            confirmed = False
            for _ in range(20):
                time.sleep(3)
                snap = _query_live(worker, api)
                live_pos = snap["position"]
                report["position_after_open"] = live_pos
                report["orders"] = api.get(f"{BACKEND_URL}/api/orders").json()
                report["fills"] = api.get(f"{BACKEND_URL}/api/fills").json()
                if str(live_pos.get("side")) in {"LONG", "SHORT"}:
                    confirmed = True
                    break
                if report["unknown"] and str(live_pos.get("side")) in {"UNKNOWN", ""}:
                    continue
            if not confirmed:
                report["stop_reason"] = "open_unknown" if report["unknown"] else "open_no_position"
                report["STEP_5_RESULT"] = "STOPPED"
                _write_report(report)
                print(f"STEP5_ONESHOT_DONE {report['stop_reason']}", flush=True)
                return 2
            closed = api.post(f"{BACKEND_URL}/api/trading/signal", json={"signal": "CLOSE"}).json()
            report["close"] = closed
            if _is_unknown(closed):
                report["unknown"] = True
            final_pos = None
            final_bal = None
            for _ in range(20):
                time.sleep(3)
                snap = _query_live(worker, api)
                final_pos = snap["position"]
                final_bal = snap["balance"]
                report["final_position"] = final_pos
                report["final_balance"] = final_bal
                report["final_status"] = {
                    "position": final_pos,
                    "worker": snap["health"].get("worker_state"),
                    "system_state": snap["status"].get("system_state"),
                }
                report["orders"] = api.get(f"{BACKEND_URL}/api/orders").json()
                report["fills"] = api.get(f"{BACKEND_URL}/api/fills").json()
                if str(final_pos.get("side")) == "FLAT":
                    break
            orders = _order_rows(report.get("orders"))
            if len(orders) > 2:
                report["duplicate_orders"] = True
                report["stop_reason"] = "third_order_risk"
                report["STEP_5_RESULT"] = "FAIL"
                _write_report(report)
                print("STEP5_ONESHOT_DONE third_order_risk", flush=True)
                return 2
            if str((final_pos or {}).get("side")) != "FLAT":
                report["stop_reason"] = "not_flat_after_close"
                report["STEP_5_RESULT"] = "FAIL"
                _write_report(report)
                print("STEP5_ONESHOT_DONE not_flat", flush=True)
                return 2
            report["stop_reason"] = "completed_flat"
            report["STEP_5_RESULT"] = "PASS"
            report["final_execution_enabled_should_be_false_after_worker_stop"] = True
            _write_report(report)
            print("STEP5_ONESHOT_DONE completed_flat", flush=True)
            return 0
    except Exception as exc:
        report["stop_reason"] = f"exception:{type(exc).__name__}"
        report["STEP_5_RESULT"] = "STOPPED"
        _write_report(report)
        print(f"STEP5_ONESHOT_DONE exception {type(exc).__name__}", flush=True)
        return 2
    finally:
        _stop_worker()
        if _SECRET_TMP_DIR is not None:
            shutil.rmtree(_SECRET_TMP_DIR, ignore_errors=True)
        report["bridge_armed_final"] = False
        report["worker_health_after"] = {"execution_enabled": False, "worker_state": "STOPPED"}
        if STATE_PATH.is_file():
            try:
                current = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                current["bridge_armed_final"] = False
                current["worker_health_after"] = {"execution_enabled": False, "worker_state": "STOPPED"}
                _write_report(current)
            except Exception:
                pass
        if backend_proc is not None:
            backend_proc.terminate()
            try:
                backend_proc.wait(timeout=10)
            except Exception:
                backend_proc.kill()
        print("WORKER_STOPPED execution_enabled_runtime_killed", flush=True)


def main() -> int:
    try:
        _require_testnet_confirmation()
    except RuntimeError as exc:
        print(f"STEP5_ONESHOT_BLOCKED {exc}", flush=True)
        return 2
    if STATE_PATH.is_file():
        try:
            prev = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
        if prev.get("stop_reason") or prev.get("STEP_5_RESULT"):
            print("STEP5_ONESHOT_DONE already_ran", flush=True)
            return 0
    print("WATCH_STARTED waiting_for_ema5break_LONG_or_SHORT", flush=True)
    signal = _wait_signal()
    return _execute(signal)


if __name__ == "__main__":
    sys.exit(main())
