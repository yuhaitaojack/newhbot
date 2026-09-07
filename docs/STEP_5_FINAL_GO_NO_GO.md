# STEP 5 — FINAL READ-ONLY GO / NO-GO

**状态：只读 GO/NO-GO 完成并停止。** 未发送真实订单。未开启 `EXECUTION_ENABLED=true`。未撤单。未改杠杆。  
**日期：** 2026-09-03  
**性质：** 认证主网只读复核（资金 + 仓位 + 官方 openOrders）

**READY_FOR_ONE_SHOT_LIVE = YES**

本轮 **没有** 下单。YES 只表示前置条件已满足，仍须下一条指令才允许发送那一笔。

---

## 本轮快照（认证只读 VERIFIED）

| 项 | 值 |
| --- | --- |
| authenticated | **true** |
| account_read | **authenticated** |
| account_connection | **VERIFIED** |
| equity | **15.049705** |
| available | **15.049705** |
| min_notional | **10** |
| FUNDS_CHECK | **PASS**（available ≥ 10） |
| BTC-USD position | **FLAT** size `0` |
| foreign_positions | **[]** |
| official openOrders BTC-USD | **0** |
| official openOrders other coins | **0** |
| worker_state | **READY** |
| recovery_reason | **null** |
| EXECUTION_ENABLED | **false** |
| bridge_armed | **false** |
| 查询失败当成 0/FLAT | **否** |

写路径本轮仍全部拦截：`buy` / `sell` / `_place_order` / `cancel` / `set_leverage` / `_execute_order_cancel` = `ReadOnlyViolation`。lost-order cancel 仍 no-op。

上次核实 available=9.249705。本轮从交易所重新读到 **15.049705**，不是口头补资。

---

## 资金门

**FUNDS_CHECK = PASS**

可用约 $15.05，高于 `$10` min notional。

即使余额约 $15：**正式一开一平仍只用约 $10 最小合理名义**，不因余额变大而加仓。滑点/手续费余量已包含在 15.05 − 10 的差额里，不作为加大仓位的理由。

---

## 开仓前状态

| 检查 | 结果 |
| --- | --- |
| BTC-USD FLAT | **PASS** |
| 无 foreign 仓 | **PASS** |
| 官方 `openOrders` BTC-USD = 0 | **PASS** |
| 官方 `openOrders` 其它币 = 0 | **PASS** |
| Worker READY / 非 Recovery | **PASS** |
| 默认 execution=false / 未武装 | **PASS** |

官方挂单来源：Hyperliquid `POST /info` `type=openOrders`（经 Connector `_api_post`）。不是 Hummingbot in-flight tracker。本快照 in-flight 亦为 0，仍不得单独当作全账户无单。

---

## 对照 READY 条件

| 条件 | 本轮 |
| --- | --- |
| authenticated account verified | YES |
| real equity/available verified | YES（15.049705 / 15.049705） |
| sufficient funds for ~$10 notional | YES |
| BTC-USD FLAT | YES |
| no foreign position | YES |
| no blocking old BTC-USD order | YES（官方 openOrders = 0） |
| no UNKNOWN | YES |
| no Recovery | YES |
| execution path armed code present, default off | YES（`saved_original_place=true`，`bridge_armed=false`） |
| 默认 execution=false | YES |

**READY_FOR_ONE_SHOT_LIVE = YES**

---

## 本轮明确没做

- 未 place / cancel / buy / sell / set_leverage
- 未把 `EXECUTION_ENABLED` 改为 true
- 未接 ema5break 自动循环
- 未改 TradingController / OrderTracker / 默认 Compose `false`
- 未发送真实订单

---

## 停止

等待下一条指令。即使本文件为 YES，**在未获明确「允许发送这一笔」之前不得下单。** 获准后仍只用约 **$10** 名义，一开一平，然后立刻把 execution 改回 false。
