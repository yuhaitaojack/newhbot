# API design

Prefix: `/api`. UI reconnect: `GET /api/status` snapshot + `/ws` incremental events.

Mutating `/api` requests in non-mock mode require `Authorization: Bearer <CONTROL_API_TOKEN>`.
In the Docker Compose frontend, Nginx injects this header from its runtime environment; the token is not compiled into browser JavaScript.
Mock mode intentionally permits local development without a token. The token is an environment secret, not a trading setting.

For authenticated read-only verification, use `docker-compose.live-readonly.example.yml` together with the local
`scripts/live_readonly_preflight.ps1`; it must keep `EXECUTION_ENABLED=false`.

## Control plane (backend)

| Method | Path | Notes |
| --- | --- | --- |
| GET | /health | Includes worker health |
| GET | /preflight | Read-only live readiness report; never arms, configures, or submits |
| GET | /market/candles | Read-only OHLCV source via Worker; strategy loop consumer only |
| GET | /status | Snapshot for UI reconnect |
| GET/PUT | /settings | SQLite persisted trading settings |
| GET | /strategy | Active strategy + parameters (`effective_value`) |
| GET | /strategy/versions | Version list |
| GET | /positions | Local mirror (not exchange truth) |
| GET | /orders | Includes UNKNOWN |
| GET | /fills | |
| GET | /trades | |
| GET | /events | |
| POST | /strategy/tick | Mock-only: evaluate one supplied snapshot, then route through Controller |
| GET | /strategy/loop | Loop status; does not start the loop |
| POST | /strategy/loop/start | Explicitly start supervised strategy loop |
| POST | /strategy/loop/stop | Stop supervised strategy loop |
| POST | /trading/start | Controller.start |
| POST | /trading/stop | Cancels opening orders, does not close |
| POST | /trading/close-and-stop | |
| POST | /trading/close-and-continue | |
| POST | /trading/emergency-stop | Latches estop |
| POST | /trading/clear-estop | Query-only unlatch; refuses unless FLAT / no open or UNKNOWN orders |
| POST | /trading/signal | Mock-only dev helper; production runtime is the strategy signal source |

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
| GET | /rpc/candles?symbol=&interval=&limit= | Read-only Hyperliquid `candleSnapshot` bridge |
| GET | /rpc/stream_events | |
| POST | /rpc/test/behavior | Mock-only test hook |
| POST | /rpc/test/query_fail | Mock-only test hook |
| POST | /rpc/test/ws_disconnect | Test hook |
| POST | /rpc/test/rest_resync | Test hook |

Adapter helpers `open_long` / `open_short` / `close_position` wrap `place_order` inside the worker. The backend Controller uses `place_order` only so there is a single execution command path.
