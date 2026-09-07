# STEP 4 续 — 真实 Hyperliquid 账户只读同步（live）

**状态：** 只读 live 账户同步已跑通并停止。未进入 STEP 5。未发送真实订单。未开启 `EXECUTION_ENABLED`。未用 FakeConnector。  
**日期：** 2026-09-02  
**Hummingbot：** 官方镜像 `hummingbot/hummingbot:version-2.16.0`  
**性质：** READ-ONLY LIVE ACCOUNT TEST

标记：

- **VERIFIED**：本会话实际跑通
- **NOT VERIFIED**：未在该条件下观察到
- **BLOCKED**：按规则停止
- **N/A**：本 STEP 禁止做的事

**是否自动进入下一阶段：否。**

前置接线：`docs/STEP_4_REPORT.md`。

---

## 结论

真实 Hyperliquid 账户状态 **可以** 经 Hummingbot v2.16.0 Connector 进入 Adapter / PositionGuard 判定，同时交易写操作仍被禁止。

| 半句 | 标记 |
| --- | --- |
| authenticated credential supplied | **是** |
| authenticated REST | **VERIFIED** |
| 当前配置 symbol（BTC-USD）仓位 | **VERIFIED = FLAT**（认证账户 `assetPositions` 为空） |
| 写操作被禁止 | **VERIFIED** |
| 实盘策略 / 开仓 | **N/A — 未执行** |

本轮 **未发生任何真实交易写操作**（`any_exchange_write=false`，`inner_place_calls=0`）。

---

## 凭证

- 报告用语：**authenticated credential supplied**
- 主账户地址（公开）：`0xae838b20cAe370555b30530b3b288F301Be6C9d4`
- secret **未**写入源码、yaml、json、Dockerfile、README、测试、本报告
- 仅存在于未跟踪 `.env`（`git check-ignore` 命中 `.gitignore:2:.env`）
- Connector 查询地址 = 主账户；签名密钥 = API wallet（agent 模式，v2.16.0 `HyperliquidPerpetualAuth`）

聊天里出现过明文 secret。测试结束后应 **轮换 API wallet 密钥**。不要把 secret 再贴进对话。

---

## 安全双保险（start 之前）

在调用 `start_network(trading_required=True)` **之前**：

| 检查 | 结果 |
| --- | --- |
| `disable_exchange_write_loops` | **VERIFIED** `write_loops_disabled_before_start=true` |
| `buy` / `sell` / `_place_order` / `cancel` / `set_leverage` / `_execute_order_cancel` | **VERIFIED** 全部 `ReadOnlyViolation` |
| `ReadOnlyGuard` 第二层 | **VERIFIED** |
| `EXECUTION_ENABLED` | **false VERIFIED** |
| Factory 拒绝 `EXECUTION_ENABLED=true` | 前置 **VERIFIED**（未在本轮再打开） |

Adapter 本地 `place_order`：**REJECTED**，错误含 read-only，`place_calls=0`。  
`cancel_order` / `set_leverage`：抛 `ExecutionDisabled`。

---

## 1. authenticated REST

**VERIFIED**

- `trading_required=True`
- `authenticator_present=true`
- `account_read=authenticated`
- `account_connection=VERIFIED`
- `_update_positions` 成功（空仓列表，不是未认证空返回）

未认证 / 查询失败 **没有** 被当成 FLAT。本轮 FLAT 来自认证后的交易所账户状态。

---

## 2. positions

**VERIFIED**

| 项 | 值 |
| --- | --- |
| 非零仓位数 | 0 |
| 配置对 BTC-USD | **FLAT** |
| foreign symbols | 无 |

映射链：Hyperliquid `clearinghouseState` → HB `account_positions` → Bridge DTO → Adapter `PositionView`。未自写第二套 position REST。

LONG / SHORT 真实快照：**NOT VERIFIED**（账户当前无仓；禁止为测试而开仓）。

---

## 3. foreign symbol

**NOT VERIFIED** — 真实账户当前没有配置对以外的仓位。未人为下单制造。

代码路径仍在：若存在 → `FOREIGN_SYMBOL_POSITION` + RECOVERING + 禁止自动平仓。

---

## 4. open orders

| 项 | 标记 |
| --- | --- |
| `in_flight_orders` 计数 | 0 **VERIFIED**（本进程 tracker） |
| tracker 空 = 交易所无挂单 | **否。不得如此解释** |
| 账户全部挂单快照 | **NOT VERIFIED**（HB v2.16.0 不 hydrate 全账户 open orders；未另写 REST） |

---

## 5. fills

| 项 | 标记 |
| --- | --- |
| Connector `_current_trade_fills` | 0 **VERIFIED**（tracker） |
| 账户历史成交全量 | **NOT VERIFIED**（HB 只处理 in-flight 关联成交；未建第二套 fill tracker） |
| SQLite `exchange_fill_id` 去重 | 前置单元 **VERIFIED**；本轮无 live fill 写入 |

---

## 6. user WebSocket

**VERIFIED（连接已建立）**

- `_user_stream_tracker_task` 运行中
- listener 未结束
- `_is_user_stream_initialized`：`last_recv_time > 0` → **true**（等待数秒后）
- 未伪造成功

本 STEP 禁止下单，因此 **没有** 用真实 order/fill 推送做事件内容验证。

---

## 7. MarketEvent

最小修复：v2.16.0 `add_listener` 需要 `EventListener`，不能传裸 method。改为官方 `EventForwarder`。修复后 `start_network` 不再因 EventListener 转换失败。

| 项 | 标记 |
| --- | --- |
| 生产订阅（OrderFilled / Cancelled / Failure / Update / TradeUpdate / Completed） | **VERIFIED**（订阅成功，无 start 异常） |
| 本轮实际收到事件 | **NOT VERIFIED**（计数 0；禁止下单制造） |
| OrderFailure ≠ 可重新开仓 | 前置映射 **VERIFIED** |

---

## 8. PositionGuard

Live Connector 快照：`exchange_side=FLAT`，`has_foreign_positions=false`，`exchange_connected=true`。

| Guard 输入 | 结果 |
| --- | --- |
| RUNNING + 本地 FLAT + 交易所 FLAT | allowed=`true`（单元对 live 快照求值） |
| RECOVERY 同样快照 | 禁止开仓 **VERIFIED** |
| 实际开仓 | **N/A** — `EXECUTION_ENABLED=false` + Guard 写拦截 |

Guard **收到了真实 Connector FLAT**，不是 FakeConnector。

---

## 9. Recovery

- `recovery_reason=null`
- `worker_state=READY`（认证 FLAT、user stream 已起、无 foreign）
- 未把未知状态标成 FLAT
- 未自动修仓 / 平仓

查询失败 / UNKNOWN 订单的 live 样本：**NOT VERIFIED**（禁止造真实订单）。

---

## 10. SQLite mirror / Exchange truth

本轮探针只跑 Worker Connector，**没有**把 live 快照写入 Backend SQLite。

| 项 | 标记 |
| --- | --- |
| Connector 为执行层真相 | **VERIFIED** |
| live SQLite 行被更新 | **NOT VERIFIED** |
| SQLite FLAT vs Connector LONG 冲突样本 | **NOT VERIFIED**（两边都是 FLAT / 未写库） |
| Guard 以交易所 side 为准（规则） | 前置 **VERIFIED** |

---

## 11. UNKNOWN

禁止创建真实订单。live UNKNOWN：**NOT VERIFIED**。  
规则未改：HB FAILED / lost / OrderFailure → 业务 UNKNOWN，不重新 place。

---

## 12. 是否发生真实交易写操作

**否。VERIFIED。**

未 place / buy / sell / cancel / close / reverse / set_leverage。lost-order 自动撤单在 start 前已 disable。

---

## 13. 用户给出的交易策略

已记录，**本 STEP 不执行**。

5 分钟 K 线、一单一仓、阴线 RSI7>45 开多 / 阳线 RSI7<55 开空、全仓 3x、ATR×2 止损、盈亏比 1:1.5 止盈 —— 仅在用户明确开始 **实盘交易测试（STEP 5+）** 且单独确认 `EXECUTION_ENABLED` 后才实现。当前仍禁止开仓。

---

## 本轮代码最小修复

`ReadOnlyHummingbotBridge._subscribe_events`：用 Hummingbot `EventForwarder` 包回调，不再把 bound method 传给 `add_listener`。不是第二套事件状态机。

---

## 汇总表

| 项 | 标记 |
| --- | --- |
| authenticated REST | **VERIFIED** |
| positions | **VERIFIED**（FLAT） |
| 当前 symbol BTC-USD | **FLAT VERIFIED** |
| LONG / SHORT live | **NOT VERIFIED** |
| foreign symbol | **NOT VERIFIED** |
| in_flight_orders tracker | **VERIFIED = 0** |
| 交易所全部挂单 | **NOT VERIFIED** |
| Connector fills tracker | **VERIFIED = 0** |
| 历史 fills 全量 | **NOT VERIFIED** |
| user WS 建立 | **VERIFIED** |
| MarketEvent 订阅 | **VERIFIED** |
| MarketEvent 真实推送内容 | **NOT VERIFIED** |
| PositionGuard 收到 Connector 状态 | **VERIFIED**（FLAT） |
| Recovery live 异常样本 | **NOT VERIFIED** |
| SQLite live mirror 写入 | **NOT VERIFIED** |
| ReadOnlyGuard | **VERIFIED** |
| lost-order cancel disable | **VERIFIED** |
| EXECUTION_ENABLED=false | **VERIFIED** |
| 真实交易写操作 | **无 VERIFIED** |
| STEP 5 | **未进入** |

---

## 停止

不开始 STEP 5。不打开 `EXECUTION_ENABLED`。不按策略下单。不把 tracker 空当成交易所无挂单。
