# STEP 2.5 报告 — Hummingbot v2.16.0 真实运行时验证

**状态：** STEP 2.5 验证完成并停止。未进入 STEP 3。未连接真实交易账户。未发送真实订单。`EXECUTION_ENABLED` 保持 `false`。  
**日期：** 2026-09-02  
**镜像：** `hummingbot/hummingbot:version-2.16.0`（digest `sha256:e222f070d42814013fb5ea7fe537926f790b259512950369da1e15a69dcbd38f`）  
**未使用** `latest`。

标记：

- **VERIFIED**：本会话实际执行且通过
- **NOT VERIFIED**：本会话未在该条件下运行
- **BLOCKED**：缺少认证账户，按规则停止，未用假密钥凑 PASS
- **N/A**：本 STEP 禁止做的事

**STEP 2.5 判定：PASS**（条件 A–J 均满足）。  
**是否允许自动进入 STEP 3：否。** 需用户明确下令。

---

## 1. Docker 状态

| 项 | 结果 |
| --- | --- |
| `docker version` Client / Engine | **29.7.2 VERIFIED** |
| Docker Desktop | **4.88.1 VERIFIED** |
| `docker compose version` | **v5.4.0 VERIFIED** |
| Context | `desktop-linux`（WSL2） |
| 镜像 `hummingbot/hummingbot:version-2.16.0` | **已存在并可 `docker run` VERIFIED** |
| 架构是否因 Docker 修改 | **否** |

上一会话 Docker daemon 不可用。本会话已恢复，**不是** `BLOCKED — Docker daemon unavailable`。

---

## 2. Hummingbot 版本

| 项 | 结果 |
| --- | --- |
| 镜像 tag | `version-2.16.0` **VERIFIED** |
| `/home/hummingbot/hummingbot/VERSION` | **`2.16.0` VERIFIED** |
| 镜像 Created | 2026-07-29 |

---

## 3. Python 版本

| 运行时 | 版本 | 本会话 |
| --- | --- | --- |
| 官方 Hummingbot conda | **3.13.14** | **VERIFIED**（`/opt/conda/envs/hummingbot/bin/python`） |
| 项目 Worker Dockerfile 目标 | **3.12** | 镜像 `python:3.12-slim-bookworm` = **3.12.14 VERIFIED**（单元测试 45 passed） |
| 本机开发 pytest | **3.14.5** | 仅开发机；不冒充 3.12 / 3.13 |

**是否必须统一 3.12 与 3.13.14：**

- 官方 v2.16.0 Connector **进程内** import 的已验证运行时是 **3.13.14**。
- 项目 Worker 镜像仍是 **3.12-slim**，**不含** hummingbot 包。本机 3.14 同样 `import hummingbot` 失败（预期 skip）。
- Thin Adapter 本 STEP 是在 **官方镜像内挂载 `execution-worker/app`** 验证的，没有把 Hummingbot 塞进 3.12 Worker 镜像，也没有改架构去迁就版本。
- **结论：** 若未来 Worker **进程内** 持有 `HyperliquidPerpetualDerivative`，打包层必须选官方 HB 运行时（3.13.14）或另证 3.12 可安装同一版本。这是 **STEP 3+ 的镜像/进程包装问题**，不是本 STEP 的架构变更理由。控制面 Backend 继续 3.12、继续禁止 import Hummingbot。

---

## 4. Connector import 结果

在官方镜像 `PYTHONPATH=/home/hummingbot`：

| import | 结果 |
| --- | --- |
| `HyperliquidPerpetualDerivative` | **VERIFIED** |
| `ExchangePyBase` | **VERIFIED**；Connector **是** 其子类 |
| `ClientOrderTracker` | **VERIFIED**；实例 `_order_tracker` 类型为 `ClientOrderTracker` |
| `PerpetualTrading` | **类 import VERIFIED**。Connector **不是** `PerpetualTrading` 的直接子类（`issubclass` = false）。只读 `start_network` 仍调度 `PerpetualTrading._funding_info_updater`，仓位 API 经 derivative 基类提供 |
| `MarketEvent` | **VERIFIED** |

---

## 5. Connector instantiate 结果

```
HyperliquidPerpetualDerivative(
    trading_required=False,
    trading_pairs=["BTC-USD"],
    hyperliquid_perpetual_secret_key=None,
    hyperliquid_perpetual_address=None,
)
```

| 项 | 结果 |
| --- | --- |
| instantiate | **ok VERIFIED** |
| `is_trading_required` | **False** |
| `authenticator` | **None** |
| 未提供密钥 | **VERIFIED** |
| ReadOnlyGuard 生产路径 | factory 仍包装 live connector；本 STEP **未**为验证而拆除 Guard |

`trading_required=True` + `secret_key=None`：构造函数失败  
`TypeError: Cannot convert None of type <class 'NoneType'> to bytes`  
→ **BLOCKED — requires authenticated Hyperliquid runtime**（见第 16 节）。未使用假密钥。

---

## 6. trading rules 结果

公开 `metaAndAssetCtxs`（非账户、非下单）：

| 项 | 结果 |
| --- | --- |
| `_make_network_check_request` | **ok VERIFIED** |
| `_format_trading_rules` 条数 | **510 VERIFIED** |
| BTC-USD `min_base_amount_increment` | `0.00001` |
| BTC-USD `min_price_increment` | `0.1` |
| BTC-USD `min_order_size` | `0.00001` |
| BTC-USD `min_notional_size` | `10` |
| `quantize_order_price("BTC-USD", 100.16)` | `100.2` **VERIFIED** |
| `quantize_order_amount("BTC-USD", 0.000019)` | `0.00001` **VERIFIED** |
| 网络前 `trading_rules` 长度 | **0**（须拉 public meta） |

`trading_required=False` 的 `start_network()`：**ok**；**user stream 未启动**；**status polling 未启动**。与 PHASE 4 / v2.16.0 源码一致。

---

## 7. ONEWAY 结果

`supported_position_modes()` = `[PositionMode.ONEWAY]`。  
HEDGE：**不存在 VERIFIED**。

---

## 8. cloid 运行时验证结果

方法：在官方镜像中实例化 **真实** `HyperliquidPerpetualDerivative`，将 **`_api_post` 换成 Recording stub**（返回假 `oid=4242`），`coin_to_asset={"BTC":0}`，并 **guard `buy`/`sell`**。然后调用 Worker `place_with_injected_cloid`。

**没有** Hyperliquid HTTP POST、没有真实订单、没有账户、没有认证。

| 断言 | 结果 |
| --- | --- |
| 业务 cloid | `0xabababababababababababababababab` |
| stub 捕获 `data.orders.cloid` | **同一字符串 VERIFIED** |
| `_api_post` 次数（单次 helper） | **1** |
| `buy()` / `sell()` | **0** |
| 第二个 cloid / MD5 新 id | **无** |
| stub `path_url` | `/exchange`（HB 内部路径名；**未真正发出**） |
| 返回 oid | stub `4242` |

调用链（运行时）：

```
业务 cloid
  → place_with_injected_cloid
  → HyperliquidPerpetualDerivative._place_order(order_id=业务cloid)
  → api_params["orders"]["cloid"] == 业务cloid
  → stub _api_post（无真实 POST）
```

生产 factory 的 `ReadOnlyGuard` 仍然拦截 `_place_order`。本证明是 **隔离探针 + stub transport**，不是拆掉 Guard。

Thin Adapter 在 hummingbot 可 import 时把 `TradeType` / `OrderType` / `PositionAction` 传给 `_place_order`（v2.16.0 使用 `is TradeType.BUY`）。无 hummingbot 时仍用字符串，FakeConnector 测试保持绿灯。

---

## 9. retry / renew 验证结果

| 证据 | 结果 |
| --- | --- |
| `_place_order` 源码含 `retry` / `renew` | **否 VERIFIED** |
| 单次 helper → `_api_post` 次数 | **1 VERIFIED** |
| 仓库生产代码 `OrderExecutor` / `PositionExecutor` / `renew_order` | **无匹配 VERIFIED** |
| `buy()`/`sell()` 源码 | **每次 `get_new_client_order_id` / MD5** → 继续禁止 |

第二次调用 helper 会再打一次 stub（测试主动二次调用）。Worker Adapter 的 `_submitted_cloids` 仍禁止同 cloid 二次 place。Helper **本身**无内层 retry。

---

## 10. buy / sell 静态扫描

生产路径：

- **禁止** `connector.buy()` / `connector.sell()`
- 唯一 place 辅助：`app/hummingbot_place.py` → `_place_order`
- `FakeConnector.buy`/`sell` 为 `AssertionError`
- `ReadOnlyGuard` 拦截 `buy`/`sell`/`_place_order`/`cancel`/`set_leverage`
- Backend / frontend / strategy：**无** `import hummingbot`，**无** `OrderExecutor` / `PositionExecutor`

执行链仍然是：

```
TradingController → HttpExecutionClient → Worker RPC → Thin Adapter → Connector
```

（默认 Compose：`EXECUTION_MODE=mock`。hyperliquid + 无 live flag：FakeConnector 替身。live flag：只读 + Guard + `EXECUTION_ENABLED` 禁止。）

---

## 11. Event API 验证

v2.16.0 `MarketEvent` 成员（官方镜像）：含 `OrderFilled`、`BuyOrderCompleted`、`SellOrderCompleted`、`OrderCancelled`、`OrderFailure`、`OrderUpdate`、`TradeUpdate` 等。

未来订阅方式（**本 STEP 未接入生产**）：

```
connector.add_listener(MarketEvent.OrderFilled, handler)
```

DTO 仅名称映射（`app.mapping.map_market_event_kind`），**不是**新的事件状态机：

| MarketEvent | 内部 kind | 业务含义 |
| --- | --- | --- |
| OrderFilled | `fill` | 审计/镜像 |
| Buy/SellOrderCompleted | `order_completed` | 订单完结 |
| OrderCancelled | `order_canceled` | 已撤销 |
| OrderFailure | `order_failure` | **≠ 可以重新开仓** |

`add_listener` 存在：**VERIFIED**。生产订阅：**NOT VERIFIED / 本 STEP 不做**。

---

## 12. UNKNOWN 验证

未改变 Controller / Guard 语义。

- 业务：`SUBMITTING` → 超时/异常 → `UNKNOWN` → **禁止再 place**；只查询 order / fills / position。
- HB `FAILED` / `failed` 映射为业务 `OrderStatus.UNKNOWN`（**不是 REJECTED**）。REJECTED 在三查确认「未提交」后才可能解除 reservation。
- Guard：`has_unknown_orders` 时禁止 LONG/SHORT。
- HB `lost_orders` / `OrderFailure` **不能**单独当作交易所确认无单。

测试：`test_hummingbot_failed_maps_to_business_unknown_not_rejected`；Backend `test_unknown_recovery.py` / `test_submitting_recovery.py` 仍通过。

---

## 13. 全部测试结果

| 套件 | 结果 |
| --- | --- |
| Worker（本机 3.14.5，含 Docker 探针） | **51 passed, 1 skipped** |
| skip | `test_real_connector_local_import_is_optional`（3.14 无 hummingbot 包，预期） |
| Backend（本机 3.14.5） | **40 passed** |
| Worker 单元（容器 Python **3.12.14**，忽略 Docker 探针） | **45 passed VERIFIED** |

未删除 Guard / Controller / Reservation / UNKNOWN / Recovery / Idempotency / Strategy isolation 测试。

新增探针均使用 Stub / Fake / ReadOnly。**零真实订单。**

Worker 生产 Adapter **不再实例化** `ExchangeStateStore`。未恢复自研 REST/WS / 订单 tracker / 仓位 tracker。

---

## 14. VERIFIED

- Docker daemon、Compose、官方 `version-2.16.0` 可运行
- VERSION = `2.16.0`；官方 Python **3.13.14**
- Connector import / `trading_required=False` 无密钥实例化
- ONEWAY-only；公开 trading rules + `quantize_*`
- 只读 `start_network` 不启动 user stream / status polling
- cloid 经真实 `_place_order` + stub `_api_post` 原样出现在 wire
- 无第二 cloid、无 buy/sell、无内层 retry/renew、无 OrderExecutor/PositionExecutor
- UNKNOWN / FAILED 映射与 Controller 规则仍在
- 全量安全测试通过
- 无真实订单、无真实密钥、`EXECUTION_ENABLED=false`

---

## 15. NOT VERIFIED

- 真实账户 `account_positions` / `in_flight_orders` / fills（无 user address，列表为空）
- `start_network(trading_required=True)` 的 user WS + REST backup + lost-order 轮询（构造器在无密钥时即失败）
- 生产 `add_listener` 事件接入
- 项目 Worker **3.12 进程内** `import hummingbot`（镜像未安装 HB，设计如此）
- 真实 `/exchange` HTTP（被 stub 替换，这是本 STEP 的安全要求）

---

## 16. BLOCKED

**`start_network(trading_required=True)` 无认证：** 构造失败，需要可转为 bytes 的 secret。  
**原因：** 需要真实 Hyperliquid 运行时凭证。  
**是否需要真实账户：** 是（后续若验证账户流）。  
**是否需要 Docker：** 是（已有）。  
**是否需要改 Worker 架构：** 否。  
**是否只能下一阶段验证：** 是。用户当场确认前不得提供密钥、不得发单。

此项 **不否定** 条件 A–J（只读实例化 + stub cloid 已满足本 STEP 目标）。

---

## 17. 是否允许进入 STEP 3

**不要自动进入。**

STEP 2.5 的 A–J 已满足。STEP 3 仍须用户明确指令。STEP 3 若涉及进程内 HB，还需单独决定 Worker 打包（3.12-slim vs 官方 3.13.14 镜像），且 **真实交易仍默认禁止**。

---

## 条件 A–J

| 条件 | 判定 |
| --- | --- |
| A Docker 可运行 v2.16.0 | **PASS** |
| B 安全 import / instantiate | **PASS**（`trading_required=False`） |
| C 确认为 v2.16.0 | **PASS** |
| D cloid 运行时证明 | **PASS**（stub transport） |
| E 无第二 cloid | **PASS** |
| F 无自动 retry/renew | **PASS** |
| G 无 buy/sell 路径 | **PASS** |
| H Worker 无第二套订单/持仓状态机 | **PASS** |
| I 安全测试通过 | **PASS** |
| J 无真实订单 | **PASS** |

---

## 停止

STEP 2.5 报告已写入。不开始 STEP 3。不连接真实 Hyperliquid 交易。不发送真实订单。
