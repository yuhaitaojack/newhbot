# STEP 5 — OPEN ORDER PRECHECK INVESTIGATION

**状态：调查完成并停止。** 未发送真实订单。未开启 `EXECUTION_ENABLED=true`。未撤单。未改杠杆。未接策略循环。  
**日期：** 2026-09-03  
**性质：** 只读技术调查 + 一次性 info 预检（不是第二套订单系统）

**READY_FOR_ONE_SHOT_LIVE = NO**

---

## 结论（先看这个）

| 项 | 结论 |
| --- | --- |
| Hummingbot v2.16.0 是否已有可复用的全账户挂单 API | **否。** 只有本进程 `in_flight_orders` / 按 oid 的 `orderStatus` |
| Hyperliquid 是否有可靠只读查询 | **是。** 官方 `POST /info` `type=openOrders` |
| 是否需要最小只读 probe | **是，已做。** 复用 Connector 已有 `_api_post`，一次性快照 |
| 是否形成第二套订单状态系统 | **否。** 不持久化、不进 OrderTracker、不进 TradingController |
| 推荐方案 | STEP 5 下单前跑这一次 `openOrders` 预检；空则放行该门；失败或 BTC 有单则 STOP |
| 是否仍然 BLOCKED | **是。** 资金门仍 FAIL。挂单门本快照已通过，但不能单独把 READY 改为 YES |
| 本快照 BTC-USD 交易所挂单 | **0 VERIFIED**（官方 `openOrders`） |
| FUNDS_CHECK | **FAIL**（上次认证核实 available=9.249705 &lt; min_notional=10） |
| 用户口头补资 ~15 USDC | **USER-STATED，本轮未再核实** |

---

## 1. Hummingbot v2.16.0 已有能力

**没有**可复用的「全账户未完成订单列表」。

Connector 实际能力：

| 能力 | 用途 | 能否证明盘面无旧挂单 |
| --- | --- | --- |
| `in_flight_orders` | 本进程 OrderTracker | **否** |
| `_update_order_status` → `_update_orders` | 刷新已跟踪订单 | **否** |
| `_request_order_status` / `type=orderStatus` | 已知 `oid` 查一笔 | **否**（必须先有 oid） |
| `_api_post` + `clearinghouseState` | 仓位与保证金 | 不含挂单列表 |
| 常量 `frontendOpenOrders` / `openOrders` | **不存在** | — |

v2.16.0 已使用的底层 transport：**同一** `_api_post(path_url="/info", data={type, user}, is_auth_required=False)`。  
`_update_balances` 已用该路径拉 `clearinghouseState`。缺的只是 **没有** 把官方 `openOrders` 包进 Connector 方法。

---

## 2. Hyperliquid 官方只读能力

官方文档（Info endpoint，无需 `/exchange`、无需签名下单）：

```
POST https://api.hyperliquid.xyz/info
{ "type": "openOrders", "user": "<address>" }
```

返回数组，例如 `{ coin, limitPx, oid, side, sz, timestamp }`。

同路径还有 `frontendOpenOrders`（多 trigger / TP-SL 展示字段）。本轮最小预检使用文档标题为 **Retrieve a user's open orders** 的 `openOrders`。

注意（官方说明）：必须查 **主账户地址**，不能查 API wallet / agent 地址，否则会得到空列表（假阴性）。本探针使用 Connector 的 `hyperliquid_perpetual_address`（与仓位/余额同一地址）。

这是公开 info 查询：只读、不创建订单、不修改订单。

---

## 3. 最小只读 probe（已落地，未接入状态机）

新增（一次性检查，不是 tracker）：

- `execution-worker/app/open_order_precheck.py` — `snapshot_open_orders(inner)`
- `execution-worker/scripts/step5_open_order_precheck_probe.py`
- `execution-worker/tests/test_open_order_precheck.py`

行为：

- 调用现有 `inner._api_post("/info", {type: openOrders, user: address}, is_auth_required=False)`
- 只返回计数与其它 coin 名
- `persisted=false`
- **不** 写入 Hummingbot OrderTracker / SQLite / Adapter `get_open_orders`
- **不** 调用 `get_balance`（本轮不重做资金认证）
- **不** place / cancel / leverage / buy / sell

未改：TradingController、PositionGuard、默认 `EXECUTION_ENABLED`、ReadOnlyGuard、lost-order no-op、策略、K 线。

### 本轮只读主网结果

**VERIFIED**

```
authenticated=true
account_read=authenticated
worker_state=READY
recovery_reason=null
BTC-USD=FLAT
foreign_symbols=[]
EXECUTION_ENABLED=false
bridge_armed=false
open_order_precheck.status=VERIFIED
configured_open_count=0
other_open_count=0
blocking=false
guard: buy/sell/_place_order/cancel/set_leverage = ReadOnlyViolation
```

本快照：**认证账户在官方 `openOrders` 下 BTC-USD 无未完成订单，其它 coin 也无挂单。**

---

## 4. 会不会变成第二套订单系统？

**不会**，只要继续遵守：

- 只在 STEP 5 下单前调用一次（或失败重试这一次查询）
- 不把结果存成 Worker/SQLite 真相
- 成交、UNKNOWN、对账仍走现有 Connector tracker + Controller
- 不根据该列表撤单（本轮也未撤）

若把它接到 `get_open_orders`、轮询、或本地订单表，才会变成第二套状态系统。当前没有那样做。

---

## 5. 推荐方案

1. **保留** Hummingbot OrderTracker 作为执行层 in-flight 真相（下单后的 oid/cloid）。
2. **STEP 5 开仓前**再跑一次 `snapshot_open_orders`：
   - 查询失败 → STOP（不能把失败当成无单）
   - `configured_open_count > 0` → STOP
   - 其它 coin 有单 → 记录；最小 BTC 测试可以不自动平，但应人工确认
3. **不要**为了「验证无单」而去下单或撤单。
4. 资金仍按上次认证值处理，见下节。

---

## 6. 资金（本轮不改代码、不重核）

上次 STEP 5 FINAL PRE-FLIGHT **VERIFIED**：

```
available = 9.249705
min_notional = 10
FUNDS_CHECK = FAIL
```

本轮 **没有** 再跑 `get_balance`，也 **没有** 改余额映射。  
用户说明已补到约 15 USDC：记为 **USER-STATED / NOT VERIFIED**。不能凭口头补资把 FUNDS_CHECK 改为 PASS，也不能据此下单。

**FUNDS_CHECK = FAIL**（硬阻塞仍在）。

---

## 7. 是否仍然 BLOCKED

**是。**

| 硬阻塞 | 本轮 |
| --- | --- |
| 资金 &lt; $10 min notional | **仍 BLOCKED**（未重新核实） |
| 无法证明 BTC-USD 无旧挂单 | **本快照已解除该技术缺口**（官方 `openOrders` = 0） |

两条里只要资金仍 FAIL，**READY_FOR_ONE_SHOT_LIVE 就必须是 NO**。

下次若只读再核余额 `available >= 10`，且开仓前 `openOrders` 仍为 BTC 0，才具备把 READY 改为 YES 的前提。那一步必须另开指令，且仍不得自动下单。

---

## 测试

| 套件 | 结果 |
| --- | --- |
| Backend | **53 passed** |
| Worker | **76 passed, 13 skipped**（含 5 个预检单测） |
| 只读主网 openOrders probe | **VERIFIED**（见上） |
| 真实 write | **无** |

---

## READY_FOR_ONE_SHOT_LIVE

**NO**

停止。等待下一条指令。本轮绝对没有真实下单。
