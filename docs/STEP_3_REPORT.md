# STEP 3 报告 — 生产运行时收口到 Hummingbot v2.16.0 Connector

**状态：** STEP 3 完成并停止。未进入 STEP 4。未使用真实 API secret。未发送真实订单。`EXECUTION_ENABLED` 保持 `false`。  
**日期：** 2026-09-02  
**Hummingbot：** 官方镜像 `hummingbot/hummingbot:version-2.16.0`（未使用 `latest`）

标记：

- **VERIFIED**：本会话实际跑通
- **NOT VERIFIED**：未在该条件下运行
- **BLOCKED**：需要真实认证，按规则停止，未伪造密钥
- **N/A**：本 STEP 禁止做的事

**是否自动进入下一阶段：否。**

---

## 1. STEP 3 状态

生产执行链已落地为：

```
Web UI
  → Backend API / SQLite
    → TradingController
      → PositionGuard / Reservation
        → HttpExecutionClient
          → Execution Worker（官方 HB v2.16.0 运行时）
            → Thin Adapter
              → ReadOnlyGuard
                → HyperliquidPerpetualDerivative
                  →（账户交易路径本 STEP 不启用）
```

Compose 默认 Worker：`EXECUTION_MODE=hyperliquid`，`EXECUTION_ENABLED=false`。  
Hyperliquid 模式 **不再** 用 FakeConnector 作为生产实现。  
Factory 在 `EXECUTION_ENABLED=true` 时直接拒绝。

---

## 2. Docker runtime

| 项 | 结果 |
| --- | --- |
| Docker Engine | 29.7.2 **VERIFIED** |
| 生产 Worker 镜像 | `FROM hummingbot/hummingbot:version-2.16.0` **VERIFIED**（`newhbot-execution-worker:step3` 构建并跑 `/health`） |
| 原 `python:3.12-slim` Worker 镜像 | **已替换**；不再为 HB 维持 3.12 |
| Backend 镜像 | 仍为 `python:3.12-slim`（控制面，不 import hummingbot） |

---

## 3. Hummingbot 版本

镜像内 `/home/hummingbot/hummingbot/VERSION` = **`2.16.0` VERIFIED**。

---

## 4. Python runtime

| 进程 | 版本 | 用途 |
| --- | --- | --- |
| Worker 生产容器 | **3.13.14**（官方 conda env） | 唯一允许 `import hummingbot` 的运行时 |
| Backend 容器 | **3.12** | 控制面 |
| 本机 pytest | **3.14.5** | Fake/Mock 单测；不冒充生产 |

判断（延续 STEP 2.5）：**不要把 Hummingbot 装进 Python 3.12。** 采用方案 A/B 的交集：官方 v2.16.0 运行时 + 项目 Worker 应用层。

---

## 5. Worker 镜像方案

```
FROM hummingbot/hummingbot:version-2.16.0
PYTHONPATH=/home/hummingbot:/app
pip: fastapi / uvicorn / pydantic
ENTRYPOINT []  （覆盖官方交互式 quickstart）
CMD uvicorn app.main:app :8001
ENV EXECUTION_ENABLED=false
```

Backend 独立容器，禁止 hummingbot。不引入 hummingbot-api。

---

## 6. Connector import

生产 Worker 镜像内 `HyperliquidPerpetualDerivative` import：**VERIFIED**。  
本机 3.14：**不可 import**（预期；factory 在 hyperliquid 模式会 raise）。

---

## 7. Connector instantiate

`trading_required=False`，`secret_key=None`，`address=None`。  
`authenticator is None`。**VERIFIED**（STEP 2.5 + STEP 3 factory）。

`trading_required=True` 无密钥：构造失败。**BLOCKED**（见第 27 节）。

---

## 8. Connector lifecycle

只读 `start_network()`（`trading_required=False`）：

- 可拉公开 trading rules / order book
- **不**启动 user stream
- **不**启动 status polling（账户）

Thin Adapter `connect()` 会调用 bridge `start_network`。失败不伪造成功。  
`/health` 在只读 Worker 容器内：**VERIFIED**（`execution_enabled=false`，`mode=hyperliquid`）。

---

## 9. trading rules

来源：`connector.trading_rules`（公开 meta）。  
Bridge `trading_rule()` 映射为 `InstrumentMeta`。Adapter **不** import `instrument_meta.py`。  
公开 BTC-USD 规则（STEP 2.5）：tick `0.1`，step `0.00001`，min notional `10`。**VERIFIED**

---

## 10. quantization

生产：`connector.quantize_order_price` / `quantize_order_amount`。  
`quantization.py` 仅 FakeConnector / 对照测试。

---

## 11. ONEWAY

`supported_position_modes()` 仅 `ONEWAY`。HEDGE 不存在。**VERIFIED**

---

## 12. cloid

```
业务 cloid
  → Adapter wire["cloid"]
  → place_with_injected_cloid
  → _place_order(order_id=业务cloid)
  → Hummingbot wire cloid
```

STEP 3 **生产路径不调用** `_place_order`：`EXECUTION_ENABLED=false` + `ReadOnlyGuard` + Adapter DRY_RUN 在 `connector.place` 之前返回 REJECTED。

Stub 运行时证明（STEP 2.5，本会话 Docker 测试仍绿）：cloid 原样、无第二 id、无 buy/sell、无内层 retry。

`_submitted_cloids` 保留。禁止 `buy()`/`sell()`。

---

## 13. order tracker

执行层订单：`connector.in_flight_orders` / `ClientOrderTracker`。  
Bridge `get_order` 读 in-flight。无账户时为空。  
`ExchangeStateStore` **不是**生产 Adapter 真相（仅 `tests/test_state_store.py`）。

---

## 14. position

执行层：`connector.account_positions` → clearinghouse 形状 dict → `map_clearinghouse_positions` → DTO。  
无 user address：空列表。**账户仓位 NOT VERIFIED / 需认证则 BLOCKED。**  
foreign symbol 仍使 Worker `RECOVERING`，不自动平仓。

---

## 15. fills

无认证 user stream：`get_fills()` 返回 `[]`。  
成交真相在有账户后必须来自 Connector；SQLite 只镜像。  
**Authenticated fills：NOT VERIFIED / BLOCKED without credentials.**

---

## 16. MarketEvent

`add_listener` 订阅 `OrderFilled` / `OrderCancelled` / `OrderFailure` / 完成事件。  
映射：`map_market_event_kind`。`OrderFailure` **≠** 可重新开仓。  
未实现第二套事件状态机。无账户时事件队列为空。**API VERIFIED；实盘事件 NOT VERIFIED。**

---

## 17. UNKNOWN

未改 Controller / Guard 语义。

`PENDING_SUBMISSION → SUBMITTING → UNKNOWN` 后禁止再 place；只 `get_order` / `get_fills` / `get_position`。  
HB `failed` / `OrderFailure` / `lost_orders` → 业务 **UNKNOWN**，不是 REJECTED，不能单独解除 reservation。

---

## 18. Recovery

Recovery 禁止新开仓。foreign symbol → Recovery + 原因，**不自动平**。未改。

---

## 19. Strategy isolation

`StrategyRuntime` / `strategies/example_strategy` 只出信号。Backend **无** `import hummingbot`。Frontend 无 place/buy/sell。

---

## 20. ReadOnlyGuard

生产 Hyperliquid 路径：**始终**包装真实 Connector。

拦截：**VERIFIED**（Worker 镜像内 buy/sell/_place_order/cancel/set_leverage 均为 `ReadOnlyViolation`）。  
未为测试拆除 Guard。

---

## 21. FakeConnector 使用范围

| 场景 | 是否允许 |
| --- | --- |
| 单元测试 / 安全测试显式注入 | **是** |
| `build_runtime(mode=hyperliquid)` | **否**（必须真实 HB 类） |
| Compose 生产 Worker | **否** |

Mock 模式（`EXECUTION_MODE=mock`）仍用于 Backend 单测与可选本地 mock Worker。

---

## 22. 生产 execution path

```
TradingController
  → HttpExecutionClient
    → Worker RPC
      → WorkerRuntime
        → HyperliquidExecutionAdapter
          → ReadOnlyHummingbotBridge
            → ReadOnlyGuard
              → HyperliquidPerpetualDerivative
```

`place`/`cancel`/`set_leverage` 在 Guard 与 `execution_enabled=false` 处双拦。

---

## 23. 静态扫描

| 符号 | 归属 |
| --- | --- |
| `buy(` / `sell(` | **禁止生产调用**。Guard / Fake AssertionError / 探针 |
| `_place_order` | HB 基础设施；仅 `hummingbot_place.py` + Fake 替身。生产被 Guard 拦住 |
| `_create_order` | 仅 HB 源码路径（buy/sell）；项目不调用 |
| OrderExecutor / PositionExecutor / `renew_order` | **仓库无** |
| `set_leverage` | 业务 RPC → Adapter → 只读拒绝 |
| `import hummingbot` | **仅 Worker**（readonly / place 枚举 / 探针） |
| Backend `import hummingbot` | **无** |
| `ExchangeStateStore` | 测试 helper |
| `quantization.py` / `instrument_meta.py` | Fake / 对照测试；生产走 Connector |
| `reconciliation.py` | 测试 helper |

---

## 24. 全部测试

| 套件 | 结果 |
| --- | --- |
| Worker（含 Docker 镜像与 STEP 2.5 探针） | **57 passed, 1 skipped** |
| skip | 本机 3.14 无 hummingbot 包（预期） |
| Backend | **40 passed** |

Guard / Controller / Reservation / UNKNOWN / Recovery / Idempotency / Strategy isolation / cloid / Connector adapter / Docker runtime：**保留且通过。**

---

## 25. VERIFIED

- Worker 官方 v2.16.0 运行时 + 应用层
- hyperliquid factory → 真实 Connector + ReadOnlyGuard
- `EXECUTION_ENABLED=true` 被 factory 拒绝
- Guard 拦截五类交易方法
- 公开 trading rules / quantize / ONEWAY / 只读 lifecycle
- cloid stub 链（STEP 2.5 测试仍绿）
- `/health` 只读 Worker 容器
- Backend 不 import hummingbot
- 全量安全测试
- 零真实订单、零真实密钥

---

## 26. NOT VERIFIED

- 真实账户 `account_positions` / fills / user WS
- `trading_required=True` + 有效凭证的 `start_network`
- 生产 `add_listener` 在真实成交上的回调
- 真实 `_place_order` HTTP（本 STEP 故意不发）

---

## 27. BLOCKED

**账户级 Connector 能力**需要 Hyperliquid 用户地址与可签名 secret。

- 为什么：v2.16.0 在 `trading_required=True` 时把 secret 转成 bytes；无密钥则构造失败。user stream / 私有仓位 / 私有成交同理。
- 已验证到：只读实例化、公开规则、量化、ONEWAY、Guard、Worker 镜像、HTTP health。
- 下一步若用户授权：在 **未跟踪** secret 中提供 testnet 或主网凭证，并单独确认是否允许 **只读账户同步**（仍默认禁止下单）。
- **不要现在提供 API secret。** 本报告不请求密钥。

---

## 28. 风险

- 只读 `start_network` 会访问 **公开** Hyperliquid 市场数据（非下单）。若网络策略禁止任何主网 HTTP，需在运维层限制。
- Worker 镜像绑定官方 HB **3.13.14**；Backend 仍 3.12。版本分裂是有意的。
- Thin Adapter 在 `EXECUTION_ENABLED=true` 时才会走到 `_place_order`；在未改 Guard/factory 前无法实盘。误开 env 会被 factory 拒绝。
- 无账户时 positions/fills 为空：控制面必须把「空」理解为 **未认证**，不能当成「确定无仓」除非 Guard/Recovery 规则已覆盖（UNKNOWN / 查询失败进 Recovery）。

---

## 29. 下一阶段建议

仅在用户明确下令后：

1. 可选：只读账户同步（凭证不进 Git，`EXECUTION_ENABLED` 仍 false，Guard 仍在）。
2. 再下一阶段才讨论授权实盘（单独确认主网/testnet、最小下单、回滚）。
3. 不要引入 Strategy V2 / Executor / hummingbot-api。

---

## 是否允许进入下一阶段

**允许用户稍后开始 STEP 4（只读账户或其它明确范围）。不允许本 Agent 自动进入。不允许自动连接交易账户。不允许发送真实订单。**

---

## 停止

STEP 3 报告已写入。不开始 STEP 4。不索取 API secret。不发任何真实交易请求。
