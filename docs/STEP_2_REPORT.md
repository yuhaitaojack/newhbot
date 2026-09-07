# STEP 2 报告 — Hummingbot Execution Worker 收敛重构

**状态：** STEP 2 代码收敛已落地并停止。未进入 STEP 3。未连接 Hyperliquid。未发送真实订单。`EXECUTION_ENABLED` 保持 `false`。  
**日期：** 2026-09-02  
**Hummingbot 锚点：** GitHub tag **v2.16.0**（源码审查）+ 官方镜像 `hummingbot/hummingbot:version-2.16.0`（本会话 Docker daemon **未运行**）  
**审计输入：** `docs/HUMMINGBOT_REUSE_AUDIT.md`（仓库内文件名；提示词中的 `HUMMINGBOT_REUSE_ARCHITECTURE_AUDIT.md` 不存在，以实际文件为准）、PHASE 0–4 报告、`AGENTS.md`、`PROJECT_REQUIREMENTS.md`

标记：

- **VERIFIED**：本会话实际跑通，或对照 v2.16.0 **源码**且有测试覆盖
- **NOT VERIFIED**：本会话未在目标运行时执行
- **BLOCKED**：缺少安全证明，不得当作已完成的实盘能力
- **N/A**：本 STEP 禁止做的事

**是否允许进入 STEP 3：否。**

---

## STEP 2-A 能力映射（修改前对照）

以 **v2.16.0 源码** 和 **本仓库当前代码** 为准。与 STEP 1 审计不一致处已在文中标明。

### A. Hummingbot 已经负责

| 能力 | v2.16.0 位置 | 源码事实 |
| --- | --- | --- |
| Hyperliquid perp 连接 | `HyperliquidPerpetualDerivative` | `trading_required=False` 时 authenticator 为 `None`；不启动 user stream / status polling |
| 网络 | `ExchangePyBase.start_network` / `stop_network` | `trading_required=True` 时：order book、trading rules、REST status 备份、user WS、lost-order 轮询 |
| user stream | `_iter_user_event_queue` | 读失败 sleep 1s 再听；**不**重下订单 |
| REST 备份 / lost order | status polling / `_lost_orders_update_polling_loop` | 查不到 N 次 → `FAILED` + `lost_orders`。**不等于**交易所确定无单/无成交 |
| trading rules | `_format_trading_rules` / `trading_rules` | `step=10**-szDecimals`，tick 来自 `markPx` 小数位，`MIN_NOTIONAL_SIZE=10` |
| 量化 | `quantize_order_price` / `quantize_order_amount` | 价格 5 位有效数字 + tick `ROUND_HALF_UP` |
| 持仓 | `PerpetualTrading.account_positions` / `_update_positions` | `szi>0` LONG，`<0` SHORT；REST 列表省略已平仓则删除缓存 key |
| 订单追踪 | `ClientOrderTracker` + `InFlightOrder` | 按 `client_order_id` 索引；fill `trade_id` 去重 |
| 下单（底层） | `_place_order` | `"cloid": order_id` **原样**；失败 `IOError`；**无内层 retry/renew** |
| 下单（禁止路径） | `buy()` / `sell()` | **每次 MD5 新 cloid** 再 `_create_order` |
| `_create_order` | `ExchangePyBase` | 使用传入的 `order_id`；量化；`start_tracking_order`；**一次** `_place_order`；异常标失败，不再 place |
| 撤单 | `cancel` → `_execute_cancel` / `_place_cancel` | 按 client id |
| 杠杆 | `_set_trading_pair_leverage` | `updateLeverage` |
| 仓位模式 | `supported_position_modes` | 仅 `ONEWAY` |

### B. 当前项目业务层必须负责

- `TradingController`：唯一交易入口；LONG/SHORT/CLOSE/HOLD；禁止反手；UNKNOWN 只查询不重发
- `PositionGuard`：单 symbol、单仓、FLAT、foreign、UNKNOWN、Recovery、Reservation、worker ready
- Reservation CAS、`cloid` / `intent_id` / `request_id` UNIQUE、inflight-open 唯一索引
- 业务 UNKNOWN：`PENDING_SUBMISSION → SUBMITTING → UNKNOWN` 后禁止再 place
- Recovery：禁止新开仓；foreign symbol 不自动平
- SQLite：业务订单、fills/trades 审计、position **镜像**、events、settings；**不是**交易所实时真相
- Strategy：只出四态信号；不得 import Hummingbot / 下单
- Web UI：五键控制；不得直连 Worker/Hummingbot 下单
- Mock / FakeConnector：单测与默认 DRY_RUN；**≠** 生产 Hyperliquid

### C. 两者之间必须存在的薄 Adapter

```
TradingController
  → HttpExecutionClient (DTO)
    → WorkerRuntime
      → HyperliquidExecutionAdapter
        → place_with_injected_cloid / ConnectorBridge
          → FakeConnector（本 STEP 默认 hyperliquid 替身）
          或 ReadOnlyHummingbotBridge（HUMMINGBOT_LIVE_CONNECTOR，只读，禁止 EXECUTION_ENABLED）
            → HyperliquidPerpetualDerivative（v2.16.0）
              → ExchangePyBase
                → Hyperliquid
```

Adapter 只做：DTO 映射、业务 cloid 注入、`_submitted_cloids` 不重发、DRY_RUN 拦截、foreign/ONEWAY 门闩、把 Connector 快照映射给 Backend。

### D. 当前项目可以删除的重复代码（本 STEP 已旁路生产路径）

| 模块 | 处理 |
| --- | --- |
| `ExchangeStateStore` | **生产 Adapter 不再实例化**。文件降级为测试辅助 |
| Worker REST/WS 融合状态机 + `reconciliation.compare_rest_and_hummingbot` | **生产不再比较两份仓位列表**。Connector `assetPositions` / `account_positions` 为执行层唯一仓位源 |
| `quantization.py` 作为 Adapter 权威 | **Adapter 不再 import**。生产调用 `connector.quantize_*`；FakeConnector 内部用该模块模拟 HB 公式；单测对照保留 |
| `instrument_meta.py` 作为生产交易规则 | **Adapter 不再 import**。生产规则来自 `connector.trading_rule` / 未来的 `connector.trading_rules` |
| 自研 reconnect / `sync_status` 真相 | Runtime 读 `connector.ws_connected`；Fake `start_network`/`stop_network` 为替身。真实 HB `start_network(trading_required=True)`：**NOT VERIFIED** |

**审计 vs 源码不一致（以源码/仓库为准）：**

1. 提示词文件名 `HUMMINGBOT_REUSE_ARCHITECTURE_AUDIT.md` → 仓库实际为 `docs/HUMMINGBOT_REUSE_AUDIT.md`。
2. STEP 1 写「hyperliquid 模式应指向真实 Connector」。本 STEP **不能**在 `EXECUTION_ENABLED=false`、无密钥、Docker 未运行时把默认执行器换成已认证的 `HyperliquidPerpetualDerivative`。默认 Compose 仍是 `EXECUTION_MODE=mock`；`hyperliquid` 模式无 `HUMMINGBOT_LIVE_CONNECTOR` 时用 **FakeConnector 作为 Connector 替身**，不是第二套 REST/WS 引擎。
3. `_place_order` 是私有方法。源码证明 cloid 原样传递且无内层 retry。**不得**因此再写一套下单引擎。实盘调用链运行时：**NOT VERIFIED / BLOCKED 进入 STEP 3**。

---

## 1. 修改前架构

```
WorkerRuntime
  → HyperliquidExecutionAdapter
      → ExchangeStateStore          ← 生产仓位/订单缓存真相
      → instrument_meta + quantization  ← 生产量化/规则
      → reconciliation REST vs hummingbotPositions
      → ConnectorBridge.place(wire)
          → FakeConnector 或 ReadOnlyHummingbotBridge
```

Adapter 在 `connect()` 把 REST 快照写入 Store，`get_positions` 读 Store。两份仓位列表不一致则 CONFLICT。

---

## 2. 修改后架构

```
WorkerRuntime
  → HyperliquidExecutionAdapter     ← 无 ExchangeStateStore
      → connector.start_network()   ← Fake 替身；live readonly 为 no-op
      → connector.trading_rule / quantize_*
      → connector.rest_snapshot() / get_order / get_fills / account_positions
      → place_with_injected_cloid(connector, wire)
          → connector._place_order(order_id=业务 cloid)
              → FakeConnector（测试/DRY_RUN 替身）
              → 或未来真实 HyperliquidPerpetualDerivative._place_order
```

生产查询不再经过 Worker 自研 store。SQLite（Backend）仍只保存业务订单与审计镜像。

---

## 3. 删除了哪些重复模块（生产路径）

- Adapter 生产真相：`ExchangeStateStore`
- Adapter 生产对账引擎：`compare_rest_and_hummingbot` + Fake 双列表 `hummingbotPositions`
- Adapter 生产量化/规则 import：`app.quantization`、`app.instrument_meta`
- Runtime 从 Store 读 `ws_connected` / `sync_status`

上述文件 **未从仓库删除**（测试辅助 / 对照），但生产 Adapter **AST 级确认不再 import**。

---

## 4. 哪些模块保留

- `TradingController`、`PositionGuard`、Reservation、UNIQUE 约束、Recovery
- `MockExecutionAdapter`、`FakeConnector`、`ReadOnlyGuard`
- `mapping.py`（HB/HL dict → 内部 DTO）
- `ioc_raw_price`（滑点算术）；量化交给 Connector
- Worker RPC 形状、`HttpExecutionClient`
- 业务 `_submitted_cloids`（UNKNOWN / 重复 cloid 不重发）
- `quantization.py` / `instrument_meta.py` / `state_store.py` / `reconciliation.py`：**测试辅助**
- 未引入 Strategy V2 Controller / PositionExecutor / OrderExecutor / hummingbot-api / AI / 回测 / 多策略 / 多账户 / 多币种 / K 线

---

## 5. 哪些能力交给 Hummingbot

设计上（真实 Connector 运行时）交给 HB：

- user WS、REST 备份、reconnect、lost-order 轮询（`start_network`）
- `trading_rules`、`quantize_order_price` / `quantize_order_amount`
- `account_positions`、`in_flight_orders`、fill `trade_id` 去重
- `_place_order` / cancel / leverage API

本 STEP **已在 Worker 内改成 Connector 接口**。FakeConnector 实现同一接口。真实 `HyperliquidPerpetualDerivative` 在本会话 **未作为执行器运行**（见第 14、18 节）。

---

## 6. cloid 实际调用链

```
业务 PlaceOrderRequest.cloid
  → Adapter 写入 wire["cloid"]（不生成新 id）
  → connector.place(wire)
  → place_with_injected_cloid
  → connector._place_order(order_id=cloid, ...)
```

**禁止：** `connector.buy()` / `connector.sell()`（v2.16.0 MD5 新 cloid）。

v2.16.0 `HyperliquidPerpetualDerivative._place_order`：

```python
"cloid": order_id,
```

- cloid 是否原样传递：**源码 VERIFIED**；Fake + Recording stub **测试 VERIFIED**
- 是否产生第二个 cloid：`_place_order` 路径 **否**（源码）；`buy`/`sell` 路径 **是**（故禁止）
- 隐藏 retry / renew / 第二次 place：`_place_order` **无**；`OrderExecutor.max_retries=10` **未引入**
- 实盘对真实 Connector 调用 `_place_order`：**NOT VERIFIED**（本会话未连交易所、未跑官方镜像）

Adapter 在 DRY_RUN / `execution_enabled=False` 时构建 `last_wire` 后 **不调用** `connector.place`。

---

## 7. UNKNOWN 实际调用链

```
Controller: PENDING_SUBMISSION → SUBMITTING → place RPC
  超时/异常 → UNKNOWN
  禁止再 place
  只查询：order / fills / position

Worker Adapter:
  _submitted_cloids.add(cloid) 发生在 connector.place 之前
  同 cloid 再次 place_order → 查 Connector.get_order；不二次 place
  查询失败/无结果 → 返回 UNKNOWN，error 含 will not resubmit
```

Hummingbot `PENDING_CREATE` / `FAILED` / `lost_orders` **不**映射为「可以重新开仓」。业务决策只在 Controller。测试：`test_place_exception_marks_unknown_and_does_not_retry`、Backend UNKNOWN / SUBMITTING 恢复测试。

---

## 8. Position 数据来源

| 层 | 来源 | 角色 |
| --- | --- | --- |
| 执行层 | Connector `rest_snapshot()["assetPositions"]`（Fake：`asset_positions`；未来 HB：`account_positions`） | **唯一实时真相** |
| Adapter | `map_clearinghouse_positions` → `PositionView`；foreign / ONEWAY 门闩 | 映射 + 业务门闩，不存第二份 store |
| Backend Guard | Worker DTO（Controller 传入 `exchange_side` / `has_foreign_positions`） | 开仓许可 |
| SQLite | position 镜像 / 审计 | **不是**真相源 |

---

## 9. Order 数据来源

| 层 | 来源 |
| --- | --- |
| 执行层 | Connector `in_flight_orders` / `get_order(cloid)` / snapshot `openOrders` |
| 业务层 | SQLite `orders`（cloid UNIQUE、intent_id UNIQUE、request_id UNIQUE、inflight-open） |
| Worker 幂等 | `_submitted_cloids`；不重发 |

---

## 10. Fill 数据来源

| 层 | 来源 |
| --- | --- |
| 执行层 | Connector `get_fills()`；Fake `record_fill` 按 `tid` 去重（模拟 HB `trade_id`） |
| 业务层 | SQLite `fills.exchange_fill_id` 唯一（Alembic `0003`） |

实时成交以 Connector 为准；SQLite 为审计。HB 事件总线 → DTO：本 STEP 通过 snapshot/`get_fills` 映射；真实 `MarketEvent` 订阅 **NOT VERIFIED**。

---

## 11. Controller 唯一入口证明

生产调用链只有：

```
UI / API → TradingController → HttpExecutionClient → Worker RPC → Adapter → Connector
```

| 表面 | 结果 |
| --- | --- |
| Strategy | `StrategyRuntime.evaluate` 只返回信号；`strategies/example_strategy` 只 `HOLD`；无 place/cancel/leverage/Hummingbot |
| Frontend | 无 `place_order` / `set_leverage` / `buy` / `sell` |
| Backend | 无 `import hummingbot`；`HttpExecutionClient` 只打 Worker HTTP |
| Worker `main.py` | RPC 一律进 `WorkerRuntime`（再进 Adapter） |
| Mock | 仅 `EXECUTION_MODE=mock` 测试路径；不是 Hyperliquid 生产执行器 |
| ReadOnlyGuard | live connector 探针对 `buy`/`sell`/`_place_order`/`cancel`/`set_leverage` 拦截 |

第二条交易路径：**未发现**（见第 12 节）。Worker HTTP 仍可被直接调用；产品规则是 **Backend 不得绕过 Controller 去交易**。测试覆盖 Controller/Guard/Reservation，不把 Worker RPC 当作第二控制面。

---

## 12. 静态扫描结果

全仓生产 `.py`（排除 `tests/`、`scripts/`）搜索 `buy(` `sell(` `_place_order` `create_order` `cancel` `set_leverage` `import hummingbot`：

| 文件 | 含义 |
| --- | --- |
| `hummingbot_place.py` | **唯一**调用 `_place_order` 的生产辅助；注释明确不调用 `buy`/`sell` |
| `connector_bridge.py` | Fake `_place_order` 替身；`buy`/`sell` **raise AssertionError** |
| `hummingbot_readonly.py` | 惰性 `import hummingbot`（只读实例化）；place/cancel/leverage 抛 `ReadOnlyViolation` |
| `readonly_guard.py` | 拦截名单 |
| `hyperliquid_adapter.py` / `runtime.py` / `main.py` / `mock_adapter.py` | 业务 `place_order` / `cancel_order` / `set_leverage` RPC |
| `backend/app/execution/client.py` | HTTP 转发到 Worker |
| `mapping.py` | 注释提到 v2.16.0 `buy()`/`sell()` cloid 格式 |

Backend / frontend / strategy：**无** Hummingbot import，**无** `_place_order`。

Adapter 模块 import 测试：`test_adapter_does_not_import_duplicate_infra` **VERIFIED**（无 `quantization` / `state_store` / `reconciliation` / `instrument_meta`）。

---

## 13. 测试结果

本机 Windows **Python 3.14.5**（开发执行器，**不冒充 3.12**）：

| 套件 | 结果 |
| --- | --- |
| `execution-worker` | **44 passed, 3 skipped** |
| `backend` | **40 passed** |

3 skip：`test_phase4_real_connector.py`（本机无 hummingbot 包 / Docker daemon 未运行）。

保留且仍然覆盖：

- 禁止反手、有仓拒绝新 LONG、UNKNOWN 不重发、Reservation 并发一个成功
- foreign → RECOVERING、Recovery 禁止开仓、SUBMITTING 重启 → UNKNOWN
- cloid / intent_id / request_id 唯一、Controller 入口、Strategy 不能下单、Backend 不 import Hummingbot

未删除 Guard / Controller / Reservation / UNKNOWN / Recovery / Idempotency / Strategy isolation 测试。

替换而非删除的测试：

- REST vs 自造 HB 双列表 CONFLICT → Connector 单源真相
- Store 重复 fill → FakeConnector `tid` 去重
- Store 过期 BTC → Connector `asset_positions` 省略后 Adapter 不再返回该仓

`ExchangeStateStore` 行为保留在 `tests/test_state_store.py`（明确为未使用的测试辅助）。

---

## 14. Docker 验证结果

| 项 | 结果 |
| --- | --- |
| Docker Desktop Linux engine | **NOT VERIFIED** — `npipe:////./pipe/dockerDesktopLinuxEngine` 不存在 |
| `hummingbot/hummingbot:version-2.16.0` 本会话 `docker run` | **NOT VERIFIED** |
| Worker 镜像 `python:3.12-slim` 本会话构建/跑测 | **NOT VERIFIED** |
| PHASE 4 历史（镜像拉取、只读 instantiate、`start_network` trading_required=False） | 见 `docs/PHASE_4_REPORT.md`；**不记入本会话 PASS** |

未为迁就环境改架构。

---

## 15. Python 版本验证结果

| 运行时 | 本会话 | 用途 |
| --- | --- | --- |
| 本机 `C:\Python314\python.exe` | **3.14.5 VERIFIED** | 跑 pytest；不能代表 Worker/HB |
| 项目 Worker Dockerfile | `python:3.12-slim-bookworm` | 目标 **3.12**；本会话镜像 **NOT VERIFIED** |
| Hummingbot 官方镜像 conda（PHASE 4） | **3.13.14** | v2.16.0 官方运行时；本会话 **NOT VERIFIED** |

---

## 16. VERIFIED

- Adapter 不再以 `ExchangeStateStore` 为生产真相
- Adapter 不再 import 生产量化/instrument_meta/reconciliation
- 生产量化走 `connector.quantize_*`；Fake 实现该接口
- 仓位/订单/成交查询走 Connector
- `place_with_injected_cloid` 使用业务 cloid；不调用 `buy`/`sell`
- v2.16.0 `_place_order` 源码：`cloid=order_id`，无内层 retry
- Worker 同 cloid 不二次 place；超时后 UNKNOWN
- PositionGuard / TradingController / Reservation / Mock 保留
- Backend 无 Hummingbot import
- 本机 pytest：Worker 44 passed / Backend 40 passed
- `EXECUTION_ENABLED` + live connector 仍被 factory 拒绝
- 未连主网、未用真实密钥、未发真实订单

---

## 17. NOT VERIFIED

- 本会话 Docker / 官方 HB 镜像 / Worker 3.12 容器
- 真实 `HyperliquidPerpetualDerivative._place_order` 运行
- `start_network(trading_required=True)` user WS + REST backup + lost-order 轮询
- 真实账户 `account_positions` / `in_flight_orders` / `trading_rules`
- Hummingbot `MarketEvent` 流式接入（仅 snapshot DTO）
- 官方 cancel action 名是否等于 `cancelByCloid`（沿用 STEP 1）
- Python 3.12 进程内 `import hummingbot`（Worker 镜像仍未安装 HB，设计如此）

---

## 18. BLOCKED

1. **实盘 cloid 注入运行时证明** — 源码 + Fake 已够支撑本 STEP 的薄 Adapter；**不足以**授权 STEP 3 对真实账户 `_place_order`。
2. **真实 Connector 作为唯一执行层运行时** — Docker 未运行；`EXECUTION_ENABLED` 必须保持 false。
3. **把 FakeConnector 从 hyperliquid 模式永久移除** — 在真实 Connector 可安全 `start_network` 之前，Fake 仍是不连交易所的 HB 接口替身。Mock 模式另外保留。

未自行创造第二套下单引擎。

---

## 19. 是否允许进入 STEP 3

**否。**

进入 STEP 3 前至少需要：Docker/官方镜像再验证、对 `_place_order` 注入 cloid 的运行时对照（仍不得发真实单，除非用户当场确认）、以及用户明确下令开始 STEP 3。

---

## 停止

STEP 2 报告已写入。不开始 STEP 3。不连接 Hyperliquid。不发送真实订单。
