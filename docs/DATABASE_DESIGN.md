# Database design

SQLite file: `data/newhbot.db` (WAL, `PRAGMA synchronous=FULL`, `foreign_keys=ON`, `busy_timeout=5000`).

**Exchange State > Local DB.** SQLite is the audit/control-plane store. It is not Hyperliquid (or Mock exchange) truth. The `positions` table is a **mirror/audit copy**. Recovery and Position Guard must query the execution adapter; they may compare the mirror, but they must not overwrite exchange state from SQLite.

Alembic revisions:

- `0001_initial` — core tables
- `0002_order_constraints` — unique `intent_id` / `request_id`, partial unique inflight-open index, `open_reservations`

**Production schema path:** `alembic upgrade head` then application startup. Lifespan does **not** call `Base.metadata.create_all()`. Tests may pass `create_app(..., bootstrap_schema=True)` which uses `create_all_for_tests()`.

## Tables

| Table | Role |
| --- | --- |
| settings | Single-row (`id=1`) trading settings |
| strategy_versions | Uploaded/registered strategy files |
| strategy_parameters | Per-version parameters |
| signals | LONG/SHORT/CLOSE/HOLD audit |
| orders | One intent → one `cloid` → one row. UNIQUE: `cloid`, `intent_id`, `request_id` |
| fills | Fill records |
| trades | Round-trip summaries |
| positions | Local mirror only |
| account_snapshots | Equity snapshots |
| system_events | Event log for UI snapshot + WS |
| audit_logs | User/system actions |
| open_reservations | Singleton CAS slot (`id=1`) for in-flight opens |

## Order status

| Status | Meaning |
| --- | --- |
| PENDING_SUBMISSION | Intent persisted. `place_order` has **not** been attempted. |
| SUBMITTING | `place_order` is in flight. |
| ACK / OPEN / PARTIAL / FILLED / REJECTED / CANCELED | Confirmed result. |
| UNKNOWN | Execution **was attempted** and the final result cannot be confirmed. |

UNKNOWN is cleared to REJECTED only when **all three** confirm absence: `get_order(cloid)` missing, no fill for that cloid, and position compatible with unsubmitted. Missing open orders alone is not enough.

## Open concurrency

Two overlapping LONG signals must not both `place_order`. The lock is SQLite compare-and-set:

`UPDATE open_reservations SET order_id=? WHERE id=1 AND order_id IS NULL`

plus a partial unique index: at most one non-reduce-only row per symbol in inflight statuses. Not a process-local bool.

## Settings

Trading knobs live in SQLite, not frontend localStorage, not `.env`. `.env` is infrastructure only.
