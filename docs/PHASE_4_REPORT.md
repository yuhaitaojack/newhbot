# PHASE 4 报告：Real Hummingbot Connector Integration & Read-Only Reconciliation

**状态：** PHASE 4 完成并停止。未进入 PHASE 5。未发送真实订单，未平真实仓，未改杠杆，未使用真实交易账户或私钥/API Key。  
**日期：** 2026-09-01  
**Hummingbot 锚点：** v2.16.0（官方镜像 `hummingbot/hummingbot:version-2.16.0`，镜像内 `hummingbot/VERSION` = `2.16.0`）  
**提交：** 见文末 Git

标记约定：

- **VERIFIED**：本会话实际执行且通过
- **NOT VERIFIED**：未跑通，或安全规则要求停止
- **N/A**：本阶段明确不做 / 禁止

## 1. Hummingbot v2.16.0 安装情况

| 项 | 结果 |
| --- | --- |
| Docker Hub 拉取 `hummingbot/hummingbot:version-2.16.0` | **VERIFIED**（digest `sha256:e222f070d42814013fb5ea7fe537926f790b259512950369da1e15a69dcbd38f`） |
| 镜像内版本文件 | **VERIFIED**（`/home/hummingbot/hummingbot/VERSION` = `2.16.0`） |
| 未升级 Hummingbot | **VERIFIED** |
| 将 Hummingbot 装进项目 Worker 镜像 `python:3.12-slim` | **未做**（不改架构；Worker Dockerfile 仍是 3.12-slim，默认 `FakeConnector`） |
| 本机 Windows `import hummingbot`（Python 3.14.5） | **NOT VERIFIED**（`ModuleNotFoundError`，预期） |

未把 Hummingbot 源码或密钥写入 Git。

## 2. Python 3.12 验证

| 运行时 | 版本 | 用途 |
| --- | --- | --- |
| `python:3.12-slim` | **3.12.14 VERIFIED** | 公共 `metaAndAssetCtxs`、Worker 单测 39 passed、Backend 单测 39 passed（1 skip：容器内无 Docker CLI） |
| 官方 Hummingbot 镜像 conda env | **3.13.14 VERIFIED** | v2.16.0 镜像实际运行时，不是 3.12 |
| 本机 pytest | 3.14.5 | 仅作开发机执行器；**不冒充 3.12** |

结论：项目 Worker 目标仍是 Python 3.12。真实 `HyperliquidPerpetualDerivative` 本阶段在官方 v2.16.0 镜像（Python 3.13.14）中只读验证。不能声称“Hummingbot v2.16.0 已在 Python 3.12 进程里作为 Worker 依赖跑起来”。

## 3. Connector import

在 `hummingbot/hummingbot:version-2.16.0` 中，`PYTHONPATH=/home/hummingbot`：

```
from hummingbot.connector.derivative.hyperliquid_perpetual.hyperliquid_perpetual_derivative import HyperliquidPerpetualDerivative
```

**VERIFIED**（pytest `test_real_connector_docker_import_instantiate_readonly`）。

本机 / Worker 3.12 默认环境：import 失败并 skip，不算冒充成功。

## 4. Connector instantiate

v2.16.0 构造函数（源码，非猜测）包含 `trading_required: bool = True`。本阶段实例化为：

```python
HyperliquidPerpetualDerivative(
    trading_required=False,
    trading_pairs=["BTC-USD"],
    hyperliquid_perpetual_secret_key=None,
    hyperliquid_perpetual_address=None,
)
```

**VERIFIED**：实例化成功；`is_trading_required is False`；`authenticator is None`（源码：`_trading_required` 为 False 时不创建 `HyperliquidPerpetualAuth`）。

未传入任何密钥或钱包地址。

## 5. Read-only 安全验证

源码事实：`start_network()` 仅在 `is_trading_required` 时启动 user stream、status polling、trading-rules polling，并初始化 builder fee。

官方镜像运行时探测 **VERIFIED**：

- `start_network` 成功
- `user_stream_started is False`
- `status_polling_started is False`
- `stop_network` 成功
- 探测脚本未调用 `buy` / `sell` / `_place_order` / `cancel` / `updateLeverage` / `set_leverage`

产品代码：`ReadOnlyGuard` + `ReadOnlyHummingbotBridge` 拦截交易方法。`HUMMINGBOT_LIVE_CONNECTOR=true` 且 `EXECUTION_ENABLED=true` 直接拒绝。默认仍是 Mock / FakeConnector。

全局搜索：Backend **不 import Hummingbot**。Controller 不调用 Hummingbot。真实 Connector 路径没有 `buy()` / `sell()` / `_place_order()` / `updateLeverage`。

## 6. Position mapping

标准化模型：`ExchangePosition`（Backend 只见 `PositionView`）。

`clearinghouseState.assetPositions`：

- `szi > 0` → LONG
- `szi < 0` → SHORT
- 列表中消失或 size 0 → FLAT（从 store 删除）

v2.16.0 `_update_positions` 会遍历 `account_positions` 并删除 exchange 不再报告的 key（HL 关闭仓会从 `assetPositions` 省略）。项目 store 用整表 REST 替换实现同一语义。

账户级真实 `clearinghouseState`：**NOT VERIFIED — credentials required for authenticated read-only validation**（需要 `user` 地址；禁止使用真实交易账户）。映射与对账由 **FAKE CONNECTOR** 单测覆盖。

## 7. Order mapping

标准化模型：`ExchangeOrder`。

v2.16.0 源码：`buy()`/`sell()` 把 HBOT client id 做 MD5，发送 `cloid = "0x" + md5.hexdigest()`（**0x + 32 hex = 34 字符**）。`orderUpdates` / `orderStatus` 回显 `order.cloid`，也可能缺省。

映射字段：`exchange_order_id`（oid）、`cloid`、`symbol`、`side`、`type`、`price`、`quantity`、`filled_quantity`、`reduce_only`、`status`。

真实交易所 open orders 读取：**NOT VERIFIED**（需 user）。FAKE 载荷映射 **VERIFIED**。

## 8. Fill mapping

标准化模型：`ExchangeFill`。`tid` → `fill_id`，另有 `order_id` / `cloid` / `symbol` / `side` / `price` / `quantity` / `fee` / `timestamp`。

真实 user fills：**NOT VERIFIED**（需 user）。FAKE 映射 + 去重 **VERIFIED**。

## 9. Instrument metadata

v2.16.0 `_format_trading_rules`：

- `step = 10 ** -szDecimals`，`min_order_size = step`
- `tick = 10 ** -len(markPx.split('.')[1])`
- `MIN_NOTIONAL_SIZE = 10`

官方镜像 Connector 公共请求 **VERIFIED**（508 条规则）：

| BTC-USD | 值 |
| --- | --- |
| min_base_amount_increment | 0.00001 |
| min_price_increment | 0.1 |
| min_order_size | 0.00001 |
| min_notional_size | 10 |

`python:3.12-slim` 直连公共 `metaAndAssetCtxs` **VERIFIED**：`szDecimals=5`，`markPx="78002.0"`，tick=0.1。

**MISMATCH（已记录并修正）：** PHASE 3 Adapter 占位 BTC meta 为 szDecimals=4 / tick=0.01 / min_order=0.0001。量化**算法**（数量 ROUND_DOWN、最多 5 位有效数字 + tick ROUND_HALF_UP、最低名义 10）与 v2.16.0 源码一致，不一致的是占位常数。已改为 `default_btc_instrument_meta()` 对齐本次公共快照。tick **不是**交易所常数，随 `markPx` 小数位变化，运行时应以公共 meta 刷新。

## 10. One-way

v2.16.0 `supported_position_modes()` → `[PositionMode.ONEWAY]`。实例化后 **VERIFIED**：含 ONEWAY，不含 HEDGE。系统不要求 HEDGE。无法确认真实账户模式时不得进入 READY 去开仓。

真实账户 position mode：**NOT VERIFIED**（无账户）。

## 11. REST snapshot

| 范围 | 结果 |
| --- | --- |
| 公共 `meta` / `metaAndAssetCtxs`（无认证） | **VERIFIED** |
| 账户 `clearinghouseState` / open orders / user fills | **NOT VERIFIED — credentials required for authenticated read-only validation** |

未查询任何真实交易账户。Live 只读 Bridge 对账户快照返回空列表并标记 skipped。

## 12. WebSocket

| 范围 | 结果 |
| --- | --- |
| `trading_required=False` 时 **不**启动 user stream | **VERIFIED** |
| 认证 user channel（`orderUpdates` + `user`） | **NOT VERIFIED**（源码在 `trading_required=True` 才启动，且需要地址） |
| FAKE CONNECTOR 模拟 WS 增量 | **VERIFIED** |

未订阅真实 user WebSocket。

## 13. reconnect

User WS 断线重连：**NOT VERIFIED**（无真实 user WS）。

FAKE：WS down → `DEGRADED` → 禁止新开仓 → REST resnapshot → 再 mark WS → 一致则 `READY`。**VERIFIED**。

`trading_required=False` 的 `start_network` / `stop_network`：**VERIFIED**（官方镜像）。

## 14. reconciliation

不能“REST 优先覆盖 WS”。产品行为：

1. WS 与 REST 方向冲突 → `CONFLICT`，保留 REST 侧，禁止开仓
2. 显式 REST resnapshot
3. 再比对 Hummingbot `account_positions` 等价缓存
4. 一致 → 可 READY；仍不一致 → 保持 `RECOVERING`

FAKE CONNECTOR：**VERIFIED**。真实 REST vs Hummingbot `account_positions`：**NOT VERIFIED**（无账户）。

## 15. stale position 检测

REST 省略已关闭的 BTC 时，本地不得保留 BTC。BTC+ETH 快照后只剩 ETH：BTC 删除，ETH 若非配置币种则 foreign。FAKE **VERIFIED**。真实账户：**NOT VERIFIED**。

## 16. duplicate fill 检测

Worker `ExchangeStateStore` 按 `fill_id` 去重。Backend `fills.exchange_fill_id` 唯一索引（Alembic `0003_fill_idempotency`），`FillRepository.add` 幂等。FAKE + SQLite **VERIFIED**。真实 WS 重连：**NOT VERIFIED**。

## 17. foreign position 检测

配置 `trading_pair` 仅一个。出现配置外持仓 → `RECOVERING`、禁止开仓、不自动平仓其他币种。FAKE **VERIFIED**。真实账户：**NOT VERIFIED**。

## 18. Worker READY

门禁仍在 `WorkerRuntime.place_order`：非 `READY` 拒绝开仓（HTTP 业务 REJECTED）。Live 只读 Connector 无 user WS → `DEGRADED`，不开仓。FAKE READY 门禁 **VERIFIED**。真实账户 READY：**NOT VERIFIED**。

`HUMMINGBOT_LIVE_CONNECTOR` 默认 false。打开且 import 成功时只实例化 `trading_required=False` 的只读 Bridge，绝不 `EXECUTION_ENABLED`。

## 19. 全量测试

| 套件 | 结果 |
| --- | --- |
| Backend（本机 3.14.5） | **40 passed** |
| Backend（Docker Python 3.12.14，完整仓库挂载） | **39 passed, 1 skipped**（容器内无 Docker CLI，跳过 compose config） |
| Worker（本机 3.14.5） | **41 passed, 1 skipped**（本机无 hummingbot 包的 REAL import 测试 skip；两条 Docker REAL 测试通过） |
| Worker（Docker Python 3.12.14，忽略 REAL CONNECTOR 文件） | **39 passed** |
| Frontend `npm run build` | **VERIFIED** |

FAKE CONNECTOR 与 REAL CONNECTOR 分文件，未混写。

PHASE 2 / PHASE 3 既有测试未放宽。

## 20. VERIFIED

- Docker 拉取 Hummingbot v2.16.0 官方镜像
- 镜像内 VERSION = 2.16.0
- `python:3.12-slim` = 3.12.14
- Connector import + `trading_required=False` 实例化
- `authenticator is None`；ONEWAY；非 HEDGE
- 公共 trading rules / BTC meta / 网络检查
- 只读 `start_network` 不启动 user stream；`stop_network`
- 无 `buy`/`sell`/`_place_order`/`cancel`/`updateLeverage` 调用
- FAKE：持仓/订单/成交映射、foreign、stale BTC、REST/HB 冲突、WS 降级恢复、fill 去重、READY 门禁
- 成交幂等 DB 约束
- BTC 占位 meta MISMATCH 已修正
- Backend 不依赖 Hummingbot 对象
- PHASE 2/3 回归 + frontend build

## 21. NOT VERIFIED

- Hummingbot v2.16.0 作为 **Python 3.12 Worker 进程依赖** 安装并长期运行
- 官方镜像 Python 为 3.13.14，不是 3.12
- 真实账户 `clearinghouseState` / open orders / user fills
- 认证 user WebSocket、user WS 重连
- 真实 REST snapshot vs 真实 Hummingbot `account_positions`
- 真实账户 One-way 模式确认
- 真实账户 foreign / stale position
- Worker 对真实账户进入 READY
- Docker Compose build/up 全栈（本阶段未作为交易验证）
- 浏览器 E2E

**NOT VERIFIED — credentials required for authenticated read-only validation**

## 22. N/A

- **REAL ORDER EXECUTION**
- **REAL MAINNET TRADING**
- **REAL CREDENTIALS**
- `place_order` / `buy` / `sell` / `cancel` / reduce-only / `updateLeverage` 真实调用
- 真实策略、止盈止损、K 线、回测、AI
- 多币种 / 多账户 / 多策略
- PHASE 5

## 23. 已知限制

- 官方 v2.16.0 镜像运行时是 Python 3.13；项目 Worker 镜像仍是 Python 3.12。二者未在同一进程合并。
- tick size 来自当前 `markPx` 小数位，不是固定 0.1。
- Live 只读模式故意不查账户、不启 user stream，因此不能对真实仓位宣称 READY。
- 默认 `EXECUTION_MODE=mock`，`EXECUTION_ENABLED=false`。
- `buy()`/`sell()` 仍会每次 MD5 新 cloid；未来交易接入必须继续注入我方 cloid，且不得走这两方法。

## 24. Git commit

工作树排除 `.env` 实值、密钥、SQLite、`node_modules`、Hummingbot 源码副本、pytest/pycache。

提交说明：`PHASE 4: read-only hummingbot connector and reconciliation`

**停止。不进入 PHASE 5。不发真实订单。不平真实仓。不改杠杆。不接真实策略。**
