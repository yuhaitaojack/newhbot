# Database design

SQLite file: `data/newhbot.db` (WAL, `PRAGMA synchronous=FULL`, foreign keys on).

**Exchange State > Local DB.** SQLite is the audit/control-plane store. It is not Hyperliquid (or Mock exchange) truth. The `positions` table is a **mirror/audit copy**. Recovery and Position Guard must query the execution adapter; they may compare the mirror, but they must not overwrite exchange state from SQLite.

Alembic revision: `0001_initial` (`backend/migrations/`). Application boot also runs `create_all` so tests can use in-memory SQLite. Docker backend image runs `alembic upgrade head` before uvicorn.

## Tables

| Table | Role |
| --- | --- |
| settings | Single-row (`id=1`) trading settings. Survives process restart and container recreate **if** `./data` is bind-mounted. |
| strategy_versions | Uploaded/registered strategy files |
| strategy_parameters | Per-version parameters |
| signals | LONG/SHORT/CLOSE/HOLD audit |
| orders | Intent + `request_id` + `cloid` + status including UNKNOWN / PENDING_SUBMISSION |
| fills | Fill records |
| trades | Round-trip summaries |
| positions | Local mirror only (`source` = `local_mirror` or `exchange_mirror`) |
| account_snapshots | Equity snapshots |
| system_events | Event log for UI snapshot + WS |
| audit_logs | User/system actions (settings, start/stop, ignored reverse) |

## Settings row

`trading_pair`, `leverage`, `position_percentage`, `order_type`, `limit_timeout`, `slippage`, `active_strategy`, `active_strategy_version`, `trading_enabled`, plus control flags `estop`, `close_intent`, `system_state`.

These live in SQLite, not frontend localStorage, not process memory as the source of truth, and not `.env`. `.env` is infrastructure only (`DATABASE_URL`, `EXECUTION_WORKER_URL`, log level, CORS).

## Strategy parameters

Each row: `name`, `type`, `default_value`, `current_value`, `enabled`, `min_value`, `max_value`, `description`.

- `enabled=false` → effective value = `default_value`
- `enabled=true` → effective value = `current_value`

PHASE 2 exposes read APIs. Writes that change parameters must go through an audited path (settings updates already write `audit_logs`).

## Orders and UNKNOWN

An order row is inserted **before** the execution RPC:

1. `PENDING_SUBMISSION` (intent persisted)
2. `UNKNOWN` immediately before `place_order`
3. Update from worker response, or stay UNKNOWN after `get_order(cloid)` if the RPC raised and the order cannot be proven absent-and-unexecuted

`cloid` is unique. Retries must not mint a new cloid.
