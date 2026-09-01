# API design

Prefix: `/api`. UI reconnect: `GET /api/status` snapshot + `/ws` incremental events.

## Control plane (backend)

| Method | Path | Notes |
| --- | --- | --- |
| GET | /health | Includes worker health |
| GET | /status | Snapshot for UI reconnect |
| GET/PUT | /settings | SQLite persisted trading settings |
| GET | /strategy | Active strategy + parameters (`effective_value`) |
| GET | /strategy/versions | Version list |
| GET | /positions | Local mirror (not exchange truth) |
| GET | /orders | Includes UNKNOWN |
| GET | /fills | |
| GET | /trades | |
| GET | /events | |
| POST | /trading/start | Controller.start |
| POST | /trading/stop | Cancels opening orders, does not close |
| POST | /trading/close-and-stop | |
| POST | /trading/close-and-continue | |
| POST | /trading/emergency-stop | Latches estop |
| POST | /trading/signal | Dev helper; production runtime will be internal |

Trading routes call `TradingController` only. They do not call Execution Worker.

## WebSocket `/ws`

First message: `{ "type": "hello", ... }`. Then fan-out from EventHub:

`system_status`, `strategy_status`, `position`, `order`, `fill`, `trade`, `signal`, `event`.

Clients that drop must reload `GET /api/status` (and lists) then resume WS. Do not treat WS as durable.

## Execution Worker RPC (internal)

Not published to the public internet in Compose (`expose` only). Every place request carries `request_id`, `cloid`, `timestamp`, `command`, `symbol`, `side`, `order_type`, `quantity`, `reduce_only`.

| Method | Path |
| --- | --- |
| GET | /health | ready, worker_state, execution_enabled, sync_status |
| POST | /rpc/connect | |
| POST | /rpc/disconnect | |
| POST | /rpc/configure | trading_pair / slippage / expected leverage; does not live-set leverage |
| GET | /rpc/balance | |
| GET | /rpc/available_balance | |
| GET | /rpc/positions | |
| GET | /rpc/position?symbol= | |
| GET | /rpc/open_orders | |
| GET | /rpc/order/{cloid} | |
| GET | /rpc/fills | |
| POST | /rpc/set_leverage | blocked when EXECUTION_ENABLED=false |
| POST | /rpc/place_order | |
| POST | /rpc/cancel_order | |
| GET | /rpc/market_data?symbol= | |
| GET | /rpc/stream_events | |
| POST | /rpc/test/behavior | Mock-only test hook |
| POST | /rpc/test/query_fail | Mock-only test hook |
| POST | /rpc/test/ws_disconnect | Test hook |
| POST | /rpc/test/rest_resync | Test hook |

Adapter helpers `open_long` / `open_short` / `close_position` wrap `place_order` inside the worker. The backend Controller uses `place_order` only so there is a single execution command path.
