# Hummingbot Reuse Architecture Audit（STEP 1）

**状态：** STEP 1 完成并停止。未修改核心代码。未进入 STEP 2 重构。未连接 Hyperliquid。未发送真实订单。  
**日期：** 2026-09-02  
**Hummingbot 锚点：** GitHub tag **v2.16.0**（发布 2026-07-29）  
**本仓库实际进度（以 Git 为准，不以本提示词为准）：**

| Phase | 提交 | 状态 |
| --- | --- | --- |
| PHASE 0–3 | `1411e3c` … `379cbc3` | 已完成 |
| PHASE 4 | `9604e00` | **已完成**（只读 Connector 审计 + Fake 对账）。提示词写「未进入 PHASE 4」与仓库不符。 |
| 本文件 | STEP 1 审计 | 不替代 PHASE 4 报告，也不开始 PHASE 5 |

默认仍是 `EXECUTION_MODE=mock`、`EXECUTION_ENABLED=false`。

标记：

- **VERIFIED**：本会话对照 v2.16.0 **源码**（及 PHASE 4 已跑过的只读实例化）
- **NOT VERIFIED**：未在真实账户/真实订单上运行
- **N/A**：本审计禁止做的事

---

## 0. 一句话结论

**方案 D 作为「进程边界」仍然成立；作为「执行层实现策略」已经过度自研。**

Hummingbot v2.16.0 已经成熟解决：Hyperliquid 连接、REST 备份轮询、user WebSocket、InFlight 订单追踪、成交去重、lost-order 轮询、持仓缓存、量化、trading rules、ONEWAY、杠杆 API。

本项目 PHASE 3/4 在 Worker 里又写了一套：`ExchangeStateStore`、REST/WS 对账、量化、IOC 滑点、instrument meta。这是 **重复的交易基础设施**，不是业务规则。

**不要**为此改用 Strategy V2 Controller / PositionExecutor / OrderExecutor / hummingbot-api。那些组件会自己下单、默认多 executor、自管 TP/SL，或 **失败后自动重试下单**（`OrderExecutor.max_retries=10`），会直接破坏「策略只出信号 / 禁止自动反手 / 超时不重发」。

推荐：**方案 B（修订后的 D）** — 自建控制面 + Position Guard + 业务 UNKNOWN/Reservation；Worker **变成 Hummingbot Connector 运行容器**，删除自研订单/仓位同步引擎。

---

## 1. Hummingbot v2.16.0 能力清单

来源均为 tag `v2.16.0` 源码，除非另标 PHASE 4 运行验证。

### 1.1 Connector / Exchange 运行时

| 能力 | 类 / 位置 | 源码事实 | 本项目是否该复用 |
| --- | --- | --- | --- |
| Hyperliquid perp 连接 | `HyperliquidPerpetualDerivative` | 构造参数含 `trading_required`；`authenticator` 在 False 时为 `None` | **是**（执行层唯一交易所适配） |
| 公共 meta / trading rules | `_format_trading_rules`、`metaAndAssetCtxs` | `step=10**-szDecimals`，tick 来自 `markPx` 小数位，`MIN_NOTIONAL_SIZE=10` | **是**；不要再维护第二套常数 |
| 价格量化 | `quantize_order_price` | `float(f"{price:.5g}")` + tick `ROUND_HALF_UP`（#8356） | **是**；调用 Connector，不要复制公式当生产路径 |
| 市价 | `buy()`/`sell()` | IOC 限价 ± `MARKET_ORDER_SLIPPAGE=0.05` | **复用滑点常数与量化**；**禁止**调用 `buy()`/`sell()`（每次 MD5 新 cloid） |
| 下单 | `_place_order` | `cloid` 用调用方传入的 id；`reduceOnly` 由 `PositionAction.CLOSE` | **是**：只走 `_place_order(..., order_id=我们的 cloid)` |
| 撤单 | `_place_cancel` | `type:cancel` + `cloid` 字段 | **是**（官方 action 名是否等于 `cancelByCloid`：**NOT VERIFIED** 运行） |
| 杠杆 | `_set_trading_pair_leverage` | `updateLeverage`，默认 cross | **是**；仅控制面设置，策略不得调 |
| Position mode | `supported_position_modes` | `[PositionMode.ONEWAY]`；设 HEDGE 失败 | **是** |
| 持仓 | `_update_positions` + `PerpetualTrading` | `szi>0` LONG，`<0` SHORT；关闭仓从 `assetPositions` 消失后 **删除缓存 key** | **是**；不要再自建第二份 position dict 当真相 |
| 网络启动 | `ExchangePyBase.start_network` | `trading_required=True` 时：order book + rules 轮询 + **status REST 备份** + **user WS** + **lost orders 轮询** | **是**（实盘 Worker 应 `start_network`，不要自写 WS 状态机） |
| WS 读失败 | `_iter_user_event_queue` | exception 后 sleep 1s 再听 | **是** |
| 只读实例化 | PHASE 4 官方镜像 | `trading_required=False` 时 **不**启动 user stream / status polling | **VERIFIED**（`9604e00` / PHASE 4） |

### 1.2 订单生命周期（底层）

| 能力 | 位置 | 源码事实 |
| --- | --- | --- |
| InFlight 状态 | `InFlightOrder.OrderState` | `PENDING_CREATE → OPEN / PARTIALLY_FILLED / FILLED / CANCELED / FAILED` |
| 追踪器 | `ClientOrderTracker` | `active` / TTL `cached`（30s）/ `lost`；按 `client_order_id` 索引 |
| 成交去重 | `InFlightOrder.update_with_trade_update` | 同一 `trade_id` 不二次计入 |
| 订单未找到 | `process_order_not_found` | 计数超过 `lost_order_count_limit`（默认 **3**）→ 标 `FAILED` 并移入 `lost_orders` |
| Lost 轮询 | `_lost_orders_update_polling_loop` | 继续 `_cancel_lost_orders` + `_update_lost_orders_status` |
| 事件 | `MarketEvent.*` | Created / Filled / Completed / Cancelled / Failure |
| 重启恢复 tracker | `restore_tracking_states` | 从 JSON 恢复 open/failed in-flight |

**关键安全差：** Hummingbot 把「查不到 N 次」标成 `FAILED`，**不等于**交易所上一定不存在该单。本项目的业务 UNKNOWN（超时后只查询、禁止新开仓）必须 **更保守**，不能把 HB `FAILED` 当成可以再开仓。

### 1.3 Strategy V2 / Executor — 不要当本项目策略或执行引擎

| 组件 | 源码事实 | 与本项目规则 |
| --- | --- | --- |
| `ControllerBase` | 自带 `buy()`/`sell()`/`_create_order`；`CreateExecutorAction` | 策略层会下单 → **否决作策略运行时** |
| `DirectionalTradingControllerBase` | 信号非 0 即建 Executor；`max_executors_per_side` 默认 **2**；文档/PHASE 1：默认 **HEDGE** | 多仓 + HEDGE + 自动执行 → **否决** |
| `PositionExecutor` | 开仓 + Triple Barrier TP/SL/超时；自己挂平仓单 | 止盈止损必须由策略发 `CLOSE` → **否决** |
| `OrderExecutor` | `max_retries=10`；`process_order_failed_event` **自动再下一单**；`renew_order` 会 cancel+place | 超时/失败重发新单 → **否决**（与「UNKNOWN 不重发」直接冲突） |
| `StrategyV2Base` | 长驻策略，用 Executor 下单 | 信号与执行耦合 → **否决** |
| hummingbot-api | Postgres + EMQX + docker.sock 多 bot（PHASE 1 已读 compose） | 过重、第二套订单库 → **否决** |

### 1.4 Hummingbot **没有**解决的（业务层）

- 单币种 / 单账户 / 单策略产品约束
- 「最多一个持仓」作为 **业务门闩**（HB 默认允许多 executor）
- 禁止自动反手（HB 会按信号开反向 Executor）
- UI：启动/停止/平仓并停止/平仓并继续/紧急停止
- 策略参数 Enabled/Disabled、策略版本、SQLite 审计
- 业务级「place RPC 超时后禁止再发第二张开仓单」
- 账户上 **非配置币种** 持仓：告警 + Recovery + **不自动平**
- 控制面与密钥/Connector 进程隔离

---

## 2. 当前项目能力清单

实际代码（PHASE 2–4），不是 PHASE 1 纸面设计。

### 2.1 控制面（应保留）

| 模块 | 职责 |
| --- | --- |
| `TradingController` | 唯一交易入口；LONG/SHORT/CLOSE/HOLD；反手拒绝；UNKNOWN 只查询 |
| `PositionGuard` | 纯函数：双 FLAT、无 UNKNOWN、无 reservation、非 RECOVERY、单币种、无 foreign |
| `ReservationRepository` | SQLite CAS：`open_reservations` 一行；并发 LONG 只成功一次 |
| `orders.cloid/intent_id/request_id` UNIQUE | 幂等键与审计 |
| 部分唯一索引 inflight open | 每 symbol 最多一张未完成开仓单 |
| `RecoveryManager` | 启动对账；unresolved → RECOVERY；estop 锁存 |
| SQLite settings/策略版本/审计/事件 | 持久化控制面 |
| Web UI / API | 控制与展示；不直连交易所 |
| `StrategyRuntime` | 目前 stub，只应输出四态信号 |
| `HttpExecutionClient` | Backend 只见标准 DTO，**不 import Hummingbot**（**VERIFIED** 无 `import hummingbot`） |

### 2.2 执行 Worker（部分是重复轮子）

| 模块 | 职责 | 评价 |
| --- | --- | --- |
| `MockExecutionAdapter` | PHASE 2 测试与默认 mock | **必须保留** |
| `WorkerRuntime` | 单币种门禁、READY、DRY_RUN | **保留并变薄** |
| `HyperliquidExecutionAdapter` | 映射 + DRY_RUN + 不重发 cloid | **保留为薄适配**；不要再当状态机 |
| `ConnectorBridge` / `FakeConnector` | 测试替身；禁止 `buy()`/`sell()` | Fake **仅测试** |
| `ExchangeStateStore` | 自研 REST+WS store、CONFLICT | **重复 HB tracker** |
| `quantization.py` / `ioc_price.py` / `instrument_meta.py` | 从 HB 公式抄来 | **生产应调用 Connector**；测试可留作对照 |
| `reconciliation.py` | REST vs 自造 HB 缓存 | **重复** `_update_positions`；业务层只需 foreign/冲突门闩 |
| `hummingbot_readonly.py` | PHASE 4 只读实例化 | 审计/安全探针对有用；不是交易引擎 |
| RPC `/rpc/*` | 窄接口 | **保留形状**，背后改接真实 Connector 事件 |

Worker 约 18 个 `app/*.py`、合计约 2k 行。其中 state_store + quantization + reconciliation + instrument_meta + Fake 快照逻辑，是「第二个交易引擎」的主体。

---

## 3. 重复实现清单（分类 A–E）

分类：

- **A** HB 已成熟 → 优先删除/替换为 HB
- **B** HB 底层 + 本项目业务层
- **C** HB 没有 → 自己实现
- **D** 两边都有但语义不同 → 划清边界，禁止两套状态机抢真相
- **E** 不必要复杂度 → 建议删除

| 当前模块 | 当前职责 | Hummingbot 已有 | 是否重复 | 最终处理 | 原因 |
| --- | --- | --- | --- | --- | --- |
| `HyperliquidPerpetualDerivative`（尚未作为 Worker 默认运行时） | 目标执行器 | 连接器本体 | 否 | **交给 HB** | PHASE 4 只读实例化 **VERIFIED**；实盘应 `start_network` |
| `ExchangeStateStore` | REST 快照 + WS 增量 + CONFLICT | `ClientOrderTracker` + `PerpetualTrading` + status polling + user WS | **是** | **A 删除生产路径** | 自研第二份仓位/订单 dict |
| REST snapshot / WS / reconnect（Worker） | 自研同步 | `start_network`：WS + REST 备份 + 1s 重试 | **是** | **A 交给 Connector** | 不要再写一套 user stream |
| `quantization.py` 生产调用 | 下单前取整 | `quantize_order_price` / szDecimals rules | **是** | **A 调用 Connector** | PHASE 4 已发现占位 meta MISMATCH；公式应跟实例走 |
| `ioc_price.py` | IOC 保护限价 | `MARKET_ORDER_SLIPPAGE` + `quantize_order_price` | 部分 | **B 薄封装** | 因禁止 `buy()`，仍要用常数+量化，但不要分叉规则 |
| `instrument_meta.py` | 解析 metaAndAssetCtxs | `_format_trading_rules` | **是** | **A 用 Connector.trading_rules** | 公共 HTTP 仅作对照测试 |
| `reconciliation.py` | REST vs「HB 缓存」指纹 | `_update_positions` 已按 exchange 列表删 stale | **是（引擎）** / **否（门闩）** | **A 删 Worker 对账引擎**；**C 保留 Guard 的 foreign/冲突** | 对账真相在 Connector；业务只消费结果 |
| `mapping.py` | HB/HL dict → 内部模型 | 无 DTO 给本项目 UI | 否 | **B 保留** | Backend 不得见 HB 对象 |
| `ConnectorBridge.place(cloid)` | 注入我方 cloid | `_place_order` | 薄封装 | **B 保留** | 禁止 `buy()`/`sell()` |
| FakeConnector | 单测 | HB 无本项目 Mock 契约 | 否 | **C 测试保留** | 默认 mock 仍需要 |
| `WorkerRuntime` READY | 禁止未就绪开仓 | `ready` / network status | 部分 | **B 保留门禁** | READY 应对齐 Connector 网络+业务 Guard，而不是自研 sync_status |
| 订单状态机 PENDING/SUBMITTING/UNKNOWN | 业务确认 | `PENDING_CREATE` / lost `FAILED` | **D** | **保留业务机；底层用 HB** | 见第 7 节 |
| `ClientOrderTracker` 未接入 | — | 订单追踪、fill 去重、lost | 本项目另写了 store | **A 使用 HB** | 不要平行实现 |
| Position Guard | 单仓门闩 | 无等价产品规则 | 否 | **C 保留并强化** | HB 默认多 executor |
| 禁止反手 | Controller | Controller/Executor 会反向开仓 | 否 | **C** | |
| Reservation CAS | 并发开仓锁 | 无 SQLite 业务锁 | 否 | **C 保留** | 见第 9 节 |
| `cloid` UNIQUE | 幂等与审计 | HB `buy()` **每次新 MD5 cloid** | **D** | **保留我方 cloid**；HB 只接收 | 这是本项目比 HB 更安全的一点 |
| `intent_id` / `request_id` UNIQUE | 审计/去重 | 无 | 否 | **C 保留** | 控制面幂等，不是执行引擎 |
| inflight-open 部分唯一索引 | 每币种一张开仓单 | 无 | 否 | **C 保留** | 与 Reservation 互补 |
| RecoveryManager | 控制面 RECOVERY | `restore_tracking_states` 只恢复 HB 内存单 | **D** | **C 保留业务 Recovery** | HB 重启不实现「禁止开仓直到对账」 |
| UNKNOWN 三查（order/fills/position） | 超时不重发 | lost-order 轮询可能标 FAILED | **D** | **B：查询走 Connector；决策走 Controller** | 不得用 HB FAILED 解除开仓禁令 |
| 成交同步（Backend Fill + exchange_fill_id） | UI/审计幂等 | tracker 内 `trade_id` 去重 | **B** | **SQLite 审计保留**；实时以 HB 事件为准 | PHASE 4 已加唯一约束 |
| 持仓同步（SQLite positions） | 镜像 | `account_positions` | **D** | SQLite **只镜像**；真相 Connector/交易所 | 已有注释 |
| One-way 检查 | 拒绝 hedge 载荷 | Connector 只支持 ONEWAY | **B** | Guard 消费 HB 仓位；发现双方向仍 RECOVERY | |
| `cancel` RPC | 紧急停止撤单 | Connector cancel | **B** | 经 Controller | |
| `set_leverage` | 设置杠杆 | Connector | **B** | 经 Controller，默认 DRY_RUN 拦截 | |
| Strategy V2 / PositionExecutor | 未接入（正确） | 会下单+TP/SL | 若接入则冲突 | **不要引入** | |
| OrderExecutor | 未接入 | **失败重试最多 10 次** | 若接入则危险 | **不要引入** | **VERIFIED** 源码 |
| hummingbot-api | 未接入 | 多 bot 平台 | 否 | **不要引入** | PHASE 1 |
| Backend → Hummingbot | 禁止 | — | — | **保持禁止** | 边界 |
| `readonly_guard` | PHASE 4 防误调用 | 无 | 否 | **测试/只读探针保留** | 不是生产执行路径 |

---

## 4. 可以删除的模块（STEP 2 候选，本 STEP 不删）

生产路径上应消失或降级为测试替身：

1. **`ExchangeStateStore` 作为真相源** — 由 Connector `account_positions` + `in_flight_orders` 替代。
2. **Worker 内 REST/WS 自研对账状态机** — 由 `start_network` 替代。
3. **`quantization.py` / `instrument_meta.fetch_*` 作为下单前权威** — 改为 `connector.quantize_*` 与 `_trading_rules`。
4. **`reconciliation.compare_rest_and_hummingbot` 在 Fake 双列表上的「第二交易所」** — 测试可留；生产比较若需要，应对 **一次** `clearinghouseState` 与 **Connector 已同步后的** `account_positions`，结果只进 Guard/Recovery，不写第三份 store。
5. **把 FakeConnector 当 Hyperliquid 模式默认「真执行」** — 保留 mock 模式；hyperliquid 模式应指向只读/实盘 Connector 包装，而不是永久 Fake。

**不要删：** Mock、Guard、Controller、Reservation、SQLite 审计、UI、策略隔离、`ConnectorBridge.place(cloid)` 禁令。

---

## 5. 必须保留的模块

- `PositionGuard`（强化：消费 HB/交易所快照，不自己连 HL）
- `TradingController`（唯一入口；反手禁止；UNKNOWN 不重发）
- `ReservationRepository` + inflight 唯一索引（业务「最多一个开仓意图」）
- 业务订单行：`cloid` / `intent_id` / `request_id`（审计与幂等）
- `RecoveryManager` + `system_state` 持久化
- Web UI 五键控制 + 设置/策略版本/参数开关
- `StrategyRuntime` 边界（只出 LONG/SHORT/CLOSE/HOLD）
- `HttpExecutionClient` + 内部 DTO
- Mock 适配器与 PHASE 2/3 安全测试
- Worker 进程边界（见第 10 节）

---

## 6. 应该交给 Hummingbot 的模块

在 **Execution Worker 进程内**：

- `HyperliquidPerpetualDerivative` + `start_network` / `stop_network`
- User WS + REST status polling + lost-order 轮询
- `ClientOrderTracker` / `InFlightOrder` / fill `trade_id` 去重
- `PerpetualTrading.account_positions` 与 stale 删除
- `quantize_order_price`、trading rules、`MIN_NOTIONAL_SIZE`
- `supported_position_modes` = ONEWAY
- `updateLeverage` 封装（仍只允许控制面调用）
- 市场中间价（策略只读数据，不经策略下单）

调用约定（PHASE 1/3 已由源码锁定，本审计再次确认）：

```
禁止: connector.buy() / sell()     # 每次新 MD5 cloid
禁止: OrderExecutor / PositionExecutor
允许: _place_order(..., order_id=我方 cloid)
允许: cancel(cloid) / 查询 / 事件订阅
```

---

## 7. 业务层必须自己控制的模块

见第 5 节。分层：

```
交易所订单是否存在、成交多少、仓位 szi
  → Hummingbot Connector（底层）

是否允许再开仓、是否反手、Recovery、单币种、foreign 不平仓
  → TradingController + PositionGuard（业务）
```

**UNKNOWN（最高优先级审查）**

| 层 | 行为 |
| --- | --- |
| Hummingbot | `PENDING_CREATE`；查不到 3 次 → `FAILED`+`lost_orders`；继续轮询 |
| 本项目今天 | `PENDING_SUBMISSION` → `SUBMITTING` → 超时 `UNKNOWN`；重启 SUBMITTING→UNKNOWN；**永不 resubmit**；三查 get_order/fills/position |

结论：**底层追踪交给 HB；业务 UNKNOWN 必须保留且更严。**  
HB `FAILED` **不得**自动变成「可以再 LONG」。只有交易所 FLAT **且** 无未完成业务意图 **且** Guard 通过才允许新开仓。

若 Worker 内嵌 Connector：`place` 应等待 `processed_by_exchange_event`（HB 已有），超时则业务 UNKNOWN，同时 **不要**再调 `_place_order`。

---

## 8. 方案 A / B / C / D 比较

用户要求的 A/B/C 与仓库 PHASE 1 的 A/B/C/D **编号不同**。下表用本审计编号，并注明 PHASE 1 对应关系。

| | **方案 A** 尽可能完整 Hummingbot 体系 | **方案 B** HB 作执行引擎 + 自建控制面/UI | **方案 C** 当前方案 D 的实现（自建 Worker 执行引擎 + Connector 外壳） |
| --- | --- | --- | --- |
| PHASE 1 对应 | A 或 C（client / V2 Controller） | **修订后的 D** | **已落地的 D（PHASE 3/4）** |
| 代码量 | 少写执行，多吃上游语义 | 中：删 Worker 重复代码，保留控制面 | 已偏大：Worker 第二套 store/量化/对账 |
| 维护成本 | 跟 V2/API/MQTT | 只跟 connector + 控制面契约 | 跟 connector **且** 跟自研同步 bug |
| 交易风险 | **高**：多 executor、TP/SL、OrderExecutor 重试 | **可控**：cloid 注入 + Guard | 中：规则对，但同步层可能与 HB 分叉 |
| 状态一致性 | HB sqlite + 我们的库 + 交易所 | 交易所 + HB 内存 + 我方审计 SQLite | 交易所 + Fake/自研 store + SQLite（三份） |
| Recovery | HB tracker restore ≠ 禁止开仓 | 业务 Recovery + HB 只读同步 | 已有业务 Recovery；Worker 另有 CONFLICT |
| UNKNOWN | 无业务「不重发」 | 业务 UNKNOWN + HB 追踪 | 已实现业务 UNKNOWN；底层未接 HB tracker |
| Order lifecycle | Executor 自管 | HB InFlight + 业务行 | 业务行 + Fake 订单 dict |
| WS / reconnect | HB | HB `start_network` | 自研 / Fake；真实 user WS **PHASE 4 NOT VERIFIED** |
| Partial fill | HB TradeUpdate | 消费 HB 事件 | Fake + 映射测试 |
| Cancel | HB / Executor | Controller → Connector cancel | RPC 已有；DRY_RUN 拦截 |
| Position tracking | PerpetualTrading | 消费 `account_positions` | `ExchangeStateStore` |
| HB 升级成本 | 绑死 V2 策略格式 | **只回归 connector** | 回归 connector **+** 重写的公式/store |
| 策略自由度 | 低（必须 HB 策略） | **高**（四态信号） | 高（同左） |
| UI 自由度 | 差（HB client / API） | **高**（现有 SPA） | 高 |
| 核心交易规则 | **不满足**（多仓、反手、TP/SL、重试） | **满足** | **业务层满足**；执行层重复 |
| 未来接真实 HL | 快但危险 | Worker 启 `trading_required=True` + 密钥隔离 | 还要把 Fake 换成真 Connector，并扔掉自研 store |

**方案 A 否决（源码）：** `OrderExecutor` 失败重试；`PositionExecutor` Triple Barrier；Directional Controller 多 executor + 下单。

**方案 C（当前实现）否决作为终态：** 不是因为 Guard/Controller 写错，而是 Worker 重复实现了 ExchangePyBase 已经做的事。PHASE 4 只读跑通 Connector，更说明应 **接入** 而非 **仿造**。

**方案 B 推荐。** 独立 Worker 仍保留（见下）。

---

## 9. Reservation 审查

| 机制 | 是否仍必要 | 说明 |
| --- | --- | --- |
| `open_reservations` CAS | **必要** | HB 不管 FastAPI 多 worker 并发 LONG。这是业务锁，不是订单引擎。 |
| inflight-open 部分唯一索引 | **必要** | DB 层第二道「每 symbol 一张开仓单」 |
| `cloid` UNIQUE | **必要** | 我方幂等；HB `buy()` 不做这个 |
| `intent_id` UNIQUE | **必要** | 一次业务意图一行 |
| `request_id` UNIQUE | **必要** | RPC/审计去重 |
| 把 reservation 扩展成执行状态机 | **不要** | 持有到 FLAT/证明未提交即可；不要在 reservation 里同步 oid/fills |

HB **不能**替代 Reservation。可简化的是：不要再让 Worker store 参与「是否已有开仓意图」——那是 SQLite 的事。

---

## 10. Execution Worker 还要不要这么复杂？

**进程还需要。** Worker 不应删除。

理由（不是为了「边界好看」）：

1. 官方 Hummingbot 运行时与本机 Backend Python **不是同一解释器**（PHASE 4：**Worker 目标 3.12**；官方 v2.16.0 镜像实际 **3.13.14**；开发机 3.14 不能当 HB）。
2. 密钥与 Connector 不进 Backend / UI。
3. Connector/Clock 崩溃不应拖死控制面；控制面崩溃不应拆掉 in-flight 追踪（HB tracker 在 Worker 内）。
4. Windows 开发机 + Linux 容器是 PHASE 0/1 已选路径。

**Worker 内部应变成：**

```
WorkerRuntime（pair + READY + DRY_RUN）
  → 薄 Adapter（DTO ↔ HB 事件）
    → HyperliquidPerpetualDerivative.start_network()
        → ClientOrderTracker / PerpetualTrading / user WS
```

**不再需要作为生产实现：** `ExchangeStateStore`、自研 reconnect、自研 REST/WS 融合引擎。

Mock 模式继续走 `MockExecutionAdapter`，测试不依赖 Docker 里的 HB。

---

## 11. Strategy Runtime

**不要**用 Strategy V2 当策略运行时。`ControllerBase.buy/sell` 与 `CreateExecutorAction` 会下单。

保持：

```
策略文件 → evaluate() → LONG|SHORT|CLOSE|HOLD → TradingController → Guard → Worker/HB
```

以后若用 HB 只读市场数据（mid / 订单簿），可以；**不能**把策略进程接到 Connector 的下单接口。K 线 UI / 回测仍为非目标。

---

## 12. 推荐架构（STEP 2 方向，本 STEP 不实施）

```
Web UI
  → Backend API + SQLite（设置/审计/Reservation/业务订单行）
    → TradingController
      → PositionGuard（消费交易所/HB 快照，不连 HL）
        → HttpExecutionClient
          → Execution Worker
            → Hummingbot HyperliquidPerpetualDerivative
              → Hyperliquid
```

Mock 默认路径不变。`EXECUTION_ENABLED=false` 直到用户明确确认。

目标原则成立：**最大化复用成熟 Connector 能力，最小化自研交易基础设施；业务规则全部留在控制面。**

---

## 13. 推荐迁移路径（仅计划）

STEP 2 未授权，下列 **不得在本 STEP 执行**。

1. Git checkpoint（当前 `9604e00` 已是 PHASE 4 点；STEP 1 只提交本审计）。
2. Worker hyperliquid 模式：用真实 Connector + Clock/`start_network`；`place` 只 `_place_order(cloid)`。
3. Adapter 订阅 HB 事件，映射为现有 `OrderView`/`FillView`/`PositionView`。
4. 删除或旁路生产 `ExchangeStateStore`。
5. 量化改为 Connector；保留单测对照 HB 公式。
6. Guard 输入改为 Worker 查询的 HB/交易所快照（含 foreign）。
7. 全量 PHASE 2/3 安全测试必须仍绿；若删测试必须证明由 HB 机制 **等价替代**（本审计认为 Guard/反手/Reservation/UNKNOWN **没有** HB 等价物，测试不得删）。
8. 仍禁止主网/testnet 真实单，直到单独确认。

---

## 14. 风险

| 风险 | 说明 |
| --- | --- |
| 把 HB `FAILED` 当成可开仓 | 可能双开。业务层必须忽略该捷径。 |
| 引入 OrderExecutor「省事」 | 最多 10 次重试新订单。**禁止**。 |
| 引入 PositionExecutor | 自动 TP/SL，违反策略 CLOSE。 |
| 同进程 import HB 进 Backend | 密钥+UI 命运共同体；Windows/3.14。保持 Worker。 |
| 官方镜像 Python 3.13 vs Worker 3.12 | 部署要对齐一个运行时，**不要用 3.14 冒充 3.12**。 |
| `buy()` 滑入适配器 | 新 cloid = 第二张单。静态扫描应继续禁止。 |
| STEP 2 一次删太多测试替身 | 先接 HB 事件，再删 store；Mock 始终留下。 |

---

## 15. 哪些结论已通过源码验证 / NOT VERIFIED / N/A

### VERIFIED（v2.16.0 源码，本会话阅读）

- Connector 构造 / `trading_required` / `authenticator is None`
- `buy()`/`sell()` MD5 新 cloid；`_place_order` 使用传入 cloid
- `ClientOrderTracker`、lost limit=3、fill `trade_id` 去重
- `ExchangePyBase.start_network`：WS + REST 备份 + lost 轮询
- user stream 读失败 1s 重试
- `_update_positions` 删除未再报告的仓位
- ONEWAY only；量化与 MIN_NOTIONAL=10
- `PositionExecutor` TP/SL；`OrderExecutor` `max_retries=10` 失败再下单
- `ControllerBase` 可 `buy`/`sell`/CreateExecutor
- 本仓库 Guard/Controller/Reservation/UNKNOWN 实现如上
- Backend 无 `import hummingbot`
- PHASE 4：官方镜像只读实例化、公共 meta、user stream 在 `trading_required=False` 时不启动（见 `docs/PHASE_4_REPORT.md`）

### NOT VERIFIED

- 真实账户 user WS / clearinghouseState / 真实订单生命周期
- HB `cancel`+cloid 与官方 `cancelByCloid` 运行等价
- 重复 cloid 在 Hyperliquid 上的拒绝字符串
- Connector 在 **本项目 Worker Python 3.12 镜像** 内长期 `start_network`（PHASE 4 跑在官方 HB 镜像 3.13）
- 本会话 Docker daemon：`dockerDesktopLinuxEngine` 管道不存在（**当前机 Docker 未运行**；PHASE 4 当时 **VERIFIED** 可拉镜像）
- Docker Compose `up` 全栈
- STEP 2 重构后的行为

### N/A

- REAL ORDER EXECUTION / REAL MAINNET / REAL CREDENTIALS
- STEP 2 代码重构（本文件只审计）
- AI / K 线 / 回测 / 多账户 / 多策略 / 多币种

---

## 16. 对 PHASE 1「方案 D」的诚实修正

PHASE 1 选择 D 的 **正确部分**：

- 不用 hummingbot-api 全家桶
- 不用 V2 Controller/Executor 当策略
- 控制面与执行进程分离
- 策略只出信号

PHASE 1 选择 D 的 **过度延伸**（PHASE 3/4 落地后可见）：

- 「只复用 Connector」被实现成「再写一个迷你交易所同步引擎」
- 量化、仓位 store、REST/WS 对账与 Connector 内部能力重复

这不是因为 PHASE 2/3 白做：Guard、UNKNOWN、Reservation、Mock、UI **仍是产品**。重复的是 Worker 里的交易基础设施。

**最终问题答案：**

> 我们自己写的、Hummingbot 已经解决的，主要是：订单 in-flight 追踪、成交去重、user WS、REST 备份轮询、reconnect、持仓缓存与 stale 删除、trading rules、价格数量量化、ONEWAY 与杠杆 API。  
> 我们自己写的、Hummingbot **没有**可靠解决的，是：单仓门闩、禁止反手、业务 UNKNOWN 不重发、Reservation、UI 控制、策略隔离、foreign 持仓不自动平、SQLite 审计。

---

**STEP 1 停止。等待审查。不修改核心代码。不进入 STEP 2。不进入真实交易。**
