# STEP 2 — AUTHORIZED CLOSE AND STOP

**日期：** 2026-09-03  
**授权：** 用户在本会话明确授权：只平掉遗留 BTC-USD LONG，并停止执行。  
**性质：** 实盘 reduce-only 平仓一次。未开新仓。未重发 UNKNOWN OPEN。未调用 emergency-stop。未启动策略循环。未修改 Compose / Dockerfile / `.env` 默认值。未直接调用 Hyperliquid API。未调用 `connector.buy()` / `connector.sell()`。  
**本文件不含** API secret / 私钥。

**STEP_2_RESULT = FAIL**

FAIL 不是因为平仓失败。交易所 BTC-USD 已 FLAT，backend 已 STOPPED，`trading_enabled=false`。FAIL 是因为成功条件要求 `worker execution_enabled=false` 或 worker 已停止，而当前容器 `newhbot-step5-oneshot-worker` 仍在跑且 `execution_enabled=true`。`close-and-stop` 不会关掉 worker 运行时武装。按本 STEP 约束，提交后只能 GET，因此未 docker stop、未改环境变量、未重试、未旁路下单。

---

## 1. 预检（全部 GET-only，满足后才 POST）

时间约 **2026-09-03T13:16Z**（CLOSE 之前）。

### 1.1 GET http://127.0.0.1:8001/health

```json
{"status":"ok","mode":"hyperliquid","connected":true,"ready":true,"worker_state":"READY","execution_enabled":true,"trading_pair":"BTC-USD","ws_connected":true,"sync_status":"LIVE","hummingbot_version":"v2.16.0","recovery_reason":null,"foreign_symbols":[]}
```

| 要求 | 结果 |
| --- | --- |
| `connected=true` | **是** |
| `ready=true` | **是** |
| `worker_state=READY` | **是** |
| `execution_enabled=true` | **是** |
| `foreign_symbols=[]` | **是** |

### 1.2 GET /rpc/position?symbol=BTC-USD

```json
{"symbol":"BTC-USD","side":"LONG","size":"0.00013","entry_price":"78352.0","unrealized_pnl":"0.01729"}
```

当前只有 BTC-USD LONG **0.00013**。

### 1.3 GET /rpc/positions

```json
[{"symbol":"BTC-USD","side":"LONG","size":"0.00013","entry_price":"78352.0","unrealized_pnl":"0.01729"}]
```

没有其它交易对仓位。

### 1.4 GET /rpc/open_orders

```json
[]
```

挂单为空。

### 1.5 GET /rpc/open_order_precheck

```json
{"status":"VERIFIED","source":"hyperliquid_info_openOrders_via_connector_api_post","configured_pair":"BTC-USD","configured_open_count":0,"other_open_count":0,"other_coins":[],"persisted":false,"blocking":false,"error_type":null}
```

`status=VERIFIED`。BTC-USD 挂单 0。其它交易对挂单 0。

### 1.6 GET http://127.0.0.1:8000/api/status

摘要：

| 项 | 值 |
| --- | --- |
| `system_state` | **RECOVERY** |
| `trading_enabled` | true |
| `estop` | false |
| `close_intent` | null |
| position | BTC-USD LONG 0.00013 @ 78352，`source=exchange_mirror` |
| last_order | 历史 CLOSE `0x9b81cf27...` **REJECTED**（`notional 9.67707 below minimum 10`） |
| last_signal | CLOSE / reason `closed`（历史误标，见 STEP 1） |

完整 JSON：

```json
{"system_state":"RECOVERY","trading_enabled":true,"estop":false,"last_signal":"CLOSE","last_signal_reason":"closed","settings":{"trading_pair":"BTC-USD","leverage":3,"position_percentage":"69.77000000","order_type":"MARKET","limit_timeout":30,"slippage":"0.05000000","active_strategy":"ema5break","active_strategy_version":"1","trading_enabled":true,"estop":false,"close_intent":null,"system_state":"RECOVERY"},"position":{"symbol":"BTC-USD","side":"LONG","size":"0.00013","entry_price":"78352.0","unrealized_pnl":"0.01729","source":"exchange_mirror","note":"Exchange State > Local DB. This is a mirror/audit row only."},"last_order":{"id":"c21df242-3164-403a-a388-2fdd1a6ba994","intent_id":"1ed93a82-b23c-4d7d-a294-1ee6d99bbb8e","request_id":"e9348f86-bdf5-4205-8dc0-72fa50b2a26b","cloid":"0x9b81cf27d36e432da84bff99fe3e59c9","exchange_oid":null,"symbol":"BTC-USD","side":"SELL","order_type":"MARKET","quantity":"0.000130000000","reduce_only":true,"status":"REJECTED","signal_id":"73b017a3-d36f-42cf-b2f8-dfcff8dcc5c3","error_message":"notional 9.67707 below minimum 10","created_at":"2026-09-03T12:39:46"},"last_fill":null,"balance":{"equity":"15.062468","available":"11.661452","margin_used":"3.401016"},"snapshot_event_id":15,"worker_ready":true,"worker_state":"READY","sync_status":"LIVE"}
```

### 1.7 预检附带：不得重发 UNKNOWN OPEN

`GET /api/orders` 预检基线（2 笔，之后只允许再多 1 笔本次 CLOSE）：

| cloid | 方向 | reduce_only | 状态 |
| --- | --- | --- | --- |
| `0x843ccebd016d4445b4877c5a7f458ca0` | BUY OPEN | false | **UNKNOWN** |
| `0x9b81cf27d36e432da84bff99fe3e59c9` | SELL CLOSE | true | **REJECTED**（历史） |

`GET /api/fills` 预检：`[]`

代码路径确认（只读）：

- `TradingController.close_and_stop` → `_close_position(stop_after=True)` → 新 cloid 的 `_submit(reduce_only=True)`。
- `_submit` 为本次 CLOSE 生成**新** `request_id` / `intent_id` / `cloid`，不会复用 `0x843ccebd...`。
- `reconcile_after_restart` / `_reconcile_unknown` 标明 **Query-only. Never calls place_order**。
- `_cancel_opening_orders` 只对本地 `OPEN`/`PARTIAL` 做 cancel；UNKNOWN 不在 `list_open()` 里，因此不会重发也不会误撤那笔历史 OPEN。
- RECOVERY 禁止 LONG/SHORT 开仓；本调用不是 signal 开仓。

预检全部满足。继续一次 POST。

---

## 2. 唯一写操作

**只调用一次：**

`POST http://127.0.0.1:8000/api/trading/close-and-stop`

HTTP 200，耗时 **16.326s**。

### CLOSE 响应

```json
{"ok":true,"cloid":"0xc510799b02154e1d9aa5d022a3215fca","status":"OPEN"}
```

| 检查 | 结果 |
| --- | --- |
| `ok=true` | **是** |
| 不是 REJECTED | **是** |
| 不是 UNKNOWN | **是** |
| 本地映射 status | `OPEN`（Hummingbot `_place_order` 返回 tuple 时 `hummingbot_place.py` 写成 `"status": "open"`；随后交易所仓位已 FLAT、挂单为空） |

未第二次 POST。未调用 `/api/trading/emergency-stop`。未调用 `/api/trading/signal`。未调用 worker `/rpc/place_order` 以外的写接口（该 POST 仅由 backend TradingController 发出一次）。

---

## 3. 执行路径

本笔 CLOSE 走：

**TradingController** (`close_and_stop` → `_close_position` → `_submit(side=SELL, reduce_only=true, quantity=0.00013)`)  
→ **HttpExecutionClient.place_order** (`POST {worker}/rpc/place_order`)  
→ **execution-worker** `POST /rpc/place_order` → `runtime.place_order`  
→ **HyperliquidExecutionAdapter.place_order**（`wire.reduce_only=true`, `is_buy=false`）  
→ **Hummingbot Connector** `place_with_injected_cloid` → `connector._place_order`（禁止 `buy()`/`sell()`）

Worker 容器生命周期内 HTTP 写日志：

```
POST /rpc/connect     200
POST /rpc/place_order 200    ← 仅此一次，对应本次 CLOSE
```

没有第二次 `place_order`。没有 `cancel_order`。UNKNOWN OPEN `0x843ccebd...` 未被重发。

---

## 4. 提交后只读查询

### 4.1 GET worker /health

```json
{"status":"ok","mode":"hyperliquid","connected":true,"ready":true,"worker_state":"READY","execution_enabled":true,"trading_pair":"BTC-USD","ws_connected":true,"sync_status":"LIVE","hummingbot_version":"v2.16.0","recovery_reason":null,"foreign_symbols":[]}
```

**缺口：** `execution_enabled` 仍为 **true**，worker **未停止**。

### 4.2 GET worker /rpc/position?symbol=BTC-USD

```json
{"symbol":"BTC-USD","side":"FLAT","size":"0","entry_price":null,"unrealized_pnl":"0"}
```

交易所真实仓位 **FLAT**。

附带 GET `/rpc/positions` → `[]`（无任何交易对仓位）。

### 4.3 GET worker /rpc/open_orders

```json
[]
```

### 4.4 GET backend /api/status

```json
{"system_state":"STOPPED","trading_enabled":false,"estop":false,"last_signal":"CLOSE","last_signal_reason":"closed","settings":{"trading_pair":"BTC-USD","leverage":3,"position_percentage":"69.77000000","order_type":"MARKET","limit_timeout":30,"slippage":"0.05000000","active_strategy":"ema5break","active_strategy_version":"1","trading_enabled":false,"estop":false,"close_intent":null,"system_state":"STOPPED"},"position":{"symbol":"BTC-USD","side":"FLAT","size":"0","entry_price":null,"unrealized_pnl":"0","source":"exchange_mirror","note":"Exchange State > Local DB. This is a mirror/audit row only."},"last_order":{"id":"fba2e4d4-073d-44a1-9f8c-91f5fbf9862b","intent_id":"2d4ff572-1f4c-41e3-86c3-d6b43bb40c8a","request_id":"beefba77-0ac0-4efa-9298-01e4aeb728f3","cloid":"0xc510799b02154e1d9aa5d022a3215fca","exchange_oid":"534984647322","symbol":"BTC-USD","side":"SELL","order_type":"MARKET","quantity":"0.000130000000","reduce_only":true,"status":"OPEN","signal_id":null,"error_message":null,"created_at":"2026-09-03T13:18:56"},"last_fill":null,"balance":{"equity":"15.054942","available":"15.054942","margin_used":"0.000000"},"snapshot_event_id":19,"worker_ready":true,"worker_state":"READY","sync_status":"LIVE"}
```

| 项 | 值 |
| --- | --- |
| `system_state` | **STOPPED** |
| `trading_enabled` | **false** |
| `estop` | false（未走 emergency-stop） |
| 事件原因 | `close_and_stop` |
| position | **FLAT**，`margin_used=0` |
| last_order | 本次唯一 CLOSE：SELL / `reduce_only=true` / qty `0.00013` / oid `534984647322` |

### 4.5 GET backend /api/orders

共 **3** 笔：

| cloid | 方向 | reduce_only | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| `0x843ccebd016d4445b4877c5a7f458ca0` | BUY | false | UNKNOWN | 原有 OPEN，**未重发** |
| `0x9b81cf27d36e432da84bff99fe3e59c9` | SELL | true | REJECTED | 历史 CLOSE，本 STEP 未再提交 |
| `0xc510799b02154e1d9aa5d022a3215fca` | SELL | true | OPEN | **本 STEP 唯一新单** |

本轮新增订单数 = **1**（唯一 CLOSE）。没有第二笔 CLOSE，没有新 OPEN。

### 4.6 GET backend /api/fills

```json
[]
```

本地 fills 仍空。交易所仓位已 FLAT、`margin_used=0`、挂单为空，平仓成交以交易所为准。本地未镜像 fill 不作为重开仓证据。

### 4.7 GET backend /api/events

本 STEP 新增：

| id | 时间 (UTC) | 事件 |
| --- | --- | --- |
| 16 | 13:19:02 | position BTC-USD **FLAT** |
| 17 | 13:19:02 | order `0xc510799b...` status OPEN |
| 18 | 13:19:07 | position BTC-USD **FLAT** |
| 19 | 13:19:09 | **RECOVERY → STOPPED** reason `close_and_stop` |

没有 LONG/SHORT 开仓事件。没有 UNKNOWN OPEN 重发。没有 emergency_stop。

---

## 5. 成功条件核对

| 条件 | 结果 |
| --- | --- |
| CLOSE 返回 `ok=true` | **通过** |
| CLOSE 不是 REJECTED / UNKNOWN | **通过** |
| 交易所 BTC-USD `position=FLAT` | **通过** |
| `open_orders=[]` | **通过** |
| backend `system_state=STOPPED` | **通过** |
| backend `trading_enabled=false` | **通过** |
| worker `execution_enabled=false` 或 worker 已停止 | **失败**（仍 READY / `execution_enabled=true`） |
| 总订单不超过原有 OPEN + 本次唯一 CLOSE | **通过**（新增仅 1 笔 CLOSE；历史 REJECTED 仍在库中但不是本轮提交） |
| 未重发 UNKNOWN OPEN | **通过** |
| 未自动反手 | **通过** |
| 未调用 emergency-stop | **通过** |
| reduce_only SELL 平仓 | **通过** |

---

## 6. 未做事项（遵守约束）

- 未重试 CLOSE。
- 未旁路下单。
- 未直接打 Hyperliquid 私有 API。
- 未调用 `connector.buy()` / `connector.sell()`。
- 未启动策略循环。
- 未修改 Compose / Dockerfile / `.env` 默认值。
- 提交后未 docker stop worker（只允许 GET）。

---

## 7. 结论

遗留 BTC-USD LONG **0.00013** 已在交易所打成 **FLAT**。合法路径只提交了一笔 reduce-only SELL CLOSE（`0xc510799b02154e1d9aa5d022a3215fca`）。backend 已 **STOPPED** 且 `trading_enabled=false`。

整体仍判 **FAIL**：武装 worker `newhbot-step5-oneshot-worker` 还在 `127.0.0.1:8001`，`EXECUTION_ENABLED` 运行时仍为 true。这不是仓位冲突，而是执行层未解除武装。

下一步须另开明确授权后再处理 worker（例如停止该容器，且**不要**改 Compose / Dockerfile / `.env` 默认值）。在此之前：不要 Start，不要 oneshot，不要再发 OPEN/CLOSE。
