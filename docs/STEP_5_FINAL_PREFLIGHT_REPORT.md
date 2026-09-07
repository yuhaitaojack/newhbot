# STEP 5 — FINAL PRE-FLIGHT REPORT

**状态：资金/挂单核验完成并停止。** 未发送真实订单。未开启 `EXECUTION_ENABLED=true`。未接策略自动循环。  
**日期：** 2026-09-03  
**Hummingbot：** v2.16.0 Connector（本轮镜像 `newhbot-execution-worker:step4` + 只读挂载当前 `execution-worker/app`）  
**性质：** READ-ONLY MAINNET 最终预检修复

标记：

- **VERIFIED**：本会话实际跑通
- **NOT VERIFIED**：现有 Connector 能力无法在该条件下证明
- **FAIL / STOP**：不满足一开一平前置条件
- **N/A**：本轮禁止做的事

**READY_FOR_ONE_SHOT_LIVE = NO**

---

## 结论

真实账户权益映射已接到 Hummingbot 官方 `_update_balances()`，不再把空 `account: {}` 当成 0。

本轮认证只读快照：

| 项 | 值 |
| --- | --- |
| authenticated | **true VERIFIED** |
| account_read | **authenticated VERIFIED** |
| worker_state | **READY VERIFIED** |
| recovery_reason | **null VERIFIED** |
| EXECUTION_ENABLED | **false VERIFIED** |
| bridge_armed | **false VERIFIED** |
| BTC-USD | **FLAT VERIFIED** |
| foreign symbols | **none VERIFIED** |
| equity | **9.249705 VERIFIED**（Connector `USD` / `accountValue`） |
| available | **9.249705 VERIFIED**（Connector `withdrawable`） |
| min_notional | **10 VERIFIED** |
| funds_check | **FAIL**（available 9.249705 &lt; 10） |
| in-flight tracker BTC-USD | 0（**≠ 全账户挂单**） |
| exchange-wide open orders | **NOT VERIFIED** |
| 真实 place / cancel / leverage | **N/A — 未执行** |

因此 **不得** 进入一开一平。两条独立 STOP：资金不足 `$10` 最小名义；无法用现有 Connector 证明交易所 BTC-USD 无旧挂单。

---

## 1. 权益 / 可用余额映射

### 改了什么

未新建 Hyperliquid REST 状态系统。复用 v2.16.0 `HyperliquidPerpetualDerivative._update_balances()`：

- `_api_post` `type=clearinghouseState`（`USER_STATE_TYPE`）
- 非 spot 抽象模式：`_account_balances["USD"] = crossMarginSummary.accountValue`
- `_account_available_balances["USD"] = withdrawable`

`ReadOnlyHummingbotBridge` 在认证 `_refresh_account_reads` 中于 `_update_positions` 之后调用该方法，再映射到 `rest_snapshot()["account"]`。

Adapter `get_balance()`：

- 未认证 / 查询失败 → `LookupError`，**禁止**默认 0
- 缺少 `equity` / `available` 键 → 同样失败
- 失败时 Adapter 进入 Recovery（`account_read` 含 `failed` 或 `balance_query_unavailable`）

写保护未改：`buy` / `sell` / `_place_order` / `cancel` / `set_leverage` 仍 `ReadOnlyViolation`；lost-order 仍 no-op；Compose / Dockerfile 默认仍 `EXECUTION_ENABLED=false`。

### 只读主网验证

**VERIFIED**

```
authenticated=true
account_read=authenticated
equity=9.249705
available=9.249705
funds_check=FAIL
```

资金检查：`available >= min_notional(10)` 不成立。  
**STOP，不下单。** 即使后续授权一开一平，也必须先入金到至少能覆盖 `$10` 名义（另加手续费/滑点余量）。

查询失败被当成 0：**否**。本轮是认证成功后的真实 ~9.25，不是映射空洞。

---

## 2. 挂单交叉确认

### Connector 能力（源码核验）

v2.16.0 Hyperliquid Connector：

- `in_flight_orders` = **本进程 OrderTracker**
- `_update_order_status` / `_request_order_status` 只刷新 **已跟踪** 订单
- 包内 **没有** `frontendOpenOrders` 或等价的全账户挂单列表 API

按规则 **没有** 另写第二套订单 REST。

| 项 | 标记 |
| --- | --- |
| Hummingbot in-flight / adapter `get_open_orders("BTC-USD")` | **VERIFIED = 0**（tracker） |
| tracker 空 = 交易所无挂单 | **否** |
| 全账户 / BTC-USD 交易所挂单 | **NOT VERIFIED** |
| 本项目 SQLite `data/newhbot.db` | **不存在**（无本地 UNKNOWN / reservation 行可查） |

**无法确认 BTC-USD 无旧挂单 → 本次真实下单必须 STOP。**

---

## 3. 仓位再确认

**VERIFIED**（认证交易所真相）

| 项 | 值 |
| --- | --- |
| BTC-USD | FLAT size `0` |
| foreign_symbols | `[]` |
| one_way_ok | true |
| position query | 成功（失败会标 UNKNOWN / Recovery，本轮未发生） |

---

## 4. 写路径与默认开关

| 项 | 结果 |
| --- | --- |
| `buy` / `sell` / `_place_order` / `cancel` / `set_leverage` / `_execute_order_cancel` | **VERIFIED** ReadOnlyViolation |
| lost-order cancel | **VERIFIED** no-op |
| `_newhbot_original_place_order` 已保存（武装代码存在） | **VERIFIED true** |
| `bridge_armed` | **false** |
| 默认 `EXECUTION_ENABLED` | **false**（`.env` / Compose / 本探针进程） |

未 place、未 cancel、未改杠杆、未改 `AGENTS.md`、未接 `ema5break` K 线循环。

---

## 5. 测试

| 套件 | 结果 |
| --- | --- |
| Backend | **53 passed** |
| Worker | **71 passed, 13 skipped**（docker / 无本地 hummingbot 的项） |
| 只读 MAINNET preflight | **VERIFIED**（见上） |

新增单测覆盖：认证余额写入 snapshot；余额查询失败 **不** 填 0；未认证 / 缺键 `get_balance` 抛错。

---

## READY_FOR_ONE_SHOT_LIVE

对照清单：

| 条件 | 本轮 |
| --- | --- |
| authenticated account verified | YES |
| real equity/available verified | YES（9.249705 / 9.249705） |
| sufficient funds for ~$10 notional | **NO** |
| BTC-USD FLAT | YES |
| no foreign position | YES |
| no blocking old BTC-USD order | **NO**（exchange-wide **NOT VERIFIED**） |
| no UNKNOWN | YES（无本地未决单库；Worker 无 UNKNOWN 仓） |
| no Recovery | YES |
| execution path armed code verified | YES（默认未打开） |
| 默认 execution=false | YES |

**READY_FOR_ONE_SHOT_LIVE = NO**

再次授权实盘前至少还需要：

1. 账户可用资金 ≥ `$10` min notional（当前 9.25，STOP）
2. 用现有 Connector **没有**的全账户挂单能力之外的、用户可接受的认证确认方式证明 BTC-USD 无旧挂单；或接受「无法证明则继续 STOP」

在此之前不得发送真实订单。

---

## 停止

等待下一条指令。本轮绝对没有真实下单。
