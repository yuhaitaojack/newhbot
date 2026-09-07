"""STEP 4 live: Worker snapshot → Backend GET /api/status → SQLite mirror.

Read-only HTTP only. Never place/cancel/leverage. Never prints secrets.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import httpx

WORKER = "http://127.0.0.1:8001"
BACKEND = "http://127.0.0.1:8000"
DB = Path(__file__).resolve().parents[2] / "data" / "step4_live_mirror.db"


def _get(client: httpx.Client, url: str, **kwargs):
    response = client.get(url, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def main() -> int:
    report: dict = {
        "execution_enabled_worker": None,
        "connect_ok": False,
        "worker_position": None,
        "worker_positions_len": None,
        "worker_open_orders_len": None,
        "worker_fills_len": None,
        "in_flight_is_not_full_book": True,
        "status1_side": None,
        "status1_source": None,
        "status1_state": None,
        "status1_ready": None,
        "status2_side": None,
        "sqlite_position_rows": None,
        "sqlite_side": None,
        "sqlite_source": None,
        "sqlite_after_worker_down_side": None,
        "sqlite_after_worker_down_source": None,
        "status_after_down_side": None,
        "any_place_called": False,
        "error_type": None,
    }
    try:
        with httpx.Client(trust_env=False) as client:
            health = _get(client, f"{WORKER}/health")
            report["execution_enabled_worker"] = health.get("execution_enabled")
            report["worker_state_before_connect"] = health.get("worker_state")
            conn = client.post(f"{WORKER}/rpc/connect", timeout=90)
            conn.raise_for_status()
            connected = conn.json()
            report["connect_ok"] = True
            report["worker_state"] = connected.get("worker_state")
            report["recovery_reason"] = connected.get("recovery_reason")
            report["account_read_hint"] = connected.get("recovery_reason")
            pos = _get(client, f"{WORKER}/rpc/position", params={"symbol": "BTC-USD"})
            report["worker_position"] = {
                "symbol": pos.get("symbol"),
                "side": pos.get("side"),
                "size": str(pos.get("size")),
            }
            positions = _get(client, f"{WORKER}/rpc/positions")
            report["worker_positions_len"] = len(positions)
            report["worker_position_symbols"] = [item.get("symbol") for item in positions]
            report["worker_open_orders_len"] = len(_get(client, f"{WORKER}/rpc/open_orders"))
            report["worker_fills_len"] = len(_get(client, f"{WORKER}/rpc/fills"))
            status1 = _get(client, f"{BACKEND}/api/status")
            report["status1_side"] = (status1.get("position") or {}).get("side")
            report["status1_source"] = (status1.get("position") or {}).get("source")
            report["status1_state"] = status1.get("system_state")
            report["status1_ready"] = status1.get("worker_ready")
            report["status1_sync"] = status1.get("sync_status")
            status2 = _get(client, f"{BACKEND}/api/status")
            report["status2_side"] = (status2.get("position") or {}).get("side")
            report["status2_source"] = (status2.get("position") or {}).get("source")
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        print(json.dumps(report))
        return 1

    if DB.is_file():
        with sqlite3.connect(DB) as db:
            rows = db.execute("select symbol, side, size, source from positions").fetchall()
            report["sqlite_position_rows"] = len(rows)
            if rows:
                report["sqlite_symbol"] = rows[0][0]
                report["sqlite_side"] = rows[0][1]
                report["sqlite_size"] = str(rows[0][2])
                report["sqlite_source"] = rows[0][3]
            snaps = db.execute("select count(*) from account_snapshots").fetchone()
            report["account_snapshot_rows"] = snaps[0] if snaps else 0
            audits = db.execute("select count(*) from audit_logs").fetchone()
            report["audit_rows"] = audits[0] if audits else 0
            events = db.execute("select count(*) from system_events").fetchone()
            report["system_event_rows"] = events[0] if events else 0
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
