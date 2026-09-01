# PHASE 3 报告：Execution Worker / Hyperliquid Adapter 基础

**状态：** PHASE 3 完成并停止。未进入 PHASE 4。未连接 Hyperliquid 主网/testnet，未发送真实订单，未使用真实密钥或钱包。  
**日期：** 2026-09-01  
**Hummingbot 锚点：** v2.16.0（GitHub tag）  
**提交：** 见文末 Git

标记约定：

- **VERIFIED**：本会话实际执行且通过
- **NOT VERIFIED**：未跑通，或外部条件阻止
- **N/A**：本阶段明确不做 / 禁止

## 1. PHASE 3 目标

把 PHASE 2 的 Mock Execution Worker 升级为可替换的执行层：

`TradingController → ExecutionClient → Worker RPC → Adapter →（未来）Hummingbot hyperliquid_perpetual @ v2.16.0`

本阶段完成架构、映射、量化、One-way、DRY_RUN、Worker READY/恢复与测试。  
**不是开始交易。** `EXECUTION_ENABLED` 默认 `false`。代码接入 ≠ 自动交易。

## 2. Hummingbot v2.16.0 验证情况

| 项 | 结果 |
| --- | --- |
| GitHub tag `v2.16.0` 连接器源码阅读 | **VERIFIED**（本会话下载并阅读 `hyperliquid_perpetual_derivative.py` 等，研究后已删除，不进仓库） |
| 本机 `import hummingbot` | **NOT VERIFIED**（`ModuleNotFoundError`，Python 3.14.5） |
| Docker 镜像 `hummingbot/hummingbot:version-2.16.0` | **NOT VERIFIED**（PHASE 2 已记录 Docker Hub 不可达；本阶段未再伪装成功） |
| 真实/testnet 下单 | **N/A** |

## 3. Connector 研究结果（以 v2.16.0 源码为准）

来源：`hummingbot/connector/derivative/hyperliquid_perpetual/` @ tag v2.16.0。

| 主题 | 源码事实 |
| --- | --- |
| 类 | `HyperliquidPerpetualDerivative` |
| `buy()` / `sell()` | 每次 `get_new_client_order_id` 再 **MD5 → `0x`+32hex cloid**，然后 `safe_ensure_future(_create_order)` |
| 幂等 | **不能**对 `buy()`/`sell()` 重试；会变成第二张单 |
| Adapter 策略 | 只走等价于 `_place_order(..., order_id=我们的 cloid)` 的 `ConnectorBridge.place(wire)`；PHASE 3 禁止 `HUMMINGBOT_LIVE_CONNECTOR` |
| `_place_order` | `type:order`；MARKET=`tif:Ioc`；LIMIT=`Gtc`；LIMIT_MAKER=`Alo`；`reduceOnly = position_action == CLOSE`；`cloid` 字段为我们传入的 id |
| 撤单 | `type:cancel` + `cloid`（与官方 `cancelByCloid` 名称是否一致：**未运行验证**） |
| 查单 | `orderStatus`，`oid` 为 exchange id 或 cloid |
| 持仓 | `clearinghouseState`；`szi>0` LONG，`<0` SHORT；关闭仓从列表消失 |
| 模式 | `supported_position_modes → [ONEWAY]`；设 HEDGE 失败 |
| 量化价格 | 最多 5 位有效数字 + `min_price_increment` `ROUND_HALF_UP`（#8356） |
| 数量 | `step = 10 ** -szDecimals`；`min_order_size = step`；`MIN_NOTIONAL_SIZE = 10` |
| 市价滑点 | `MARKET_ORDER_SLIPPAGE = 0.05`；买 `*1.05`，卖 `*0.95` |
| 杠杆 | `updateLeverage`；默认 `isCross=True` |
| 用户 WS | 订阅 `orderUpdates` + `user`；心跳 30s；消息超时 60s |
| Connector 重试 | `_place_order` 失败即 `IOError`，方法内无再下一单。WS `_iter_user_event_queue` 断线 sleep 1s 再听，**不补单**。仍禁止业务层把 connector 内部 reconnect 当成可以 `place_order` 重放 |

## 4. Adapter 架构

```
HyperliquidExecutionAdapter  →  ConnectorBridge
MockExecutionAdapter         →  in-memory mock
WorkerRuntime                →  单币种门禁 + READY + 不重试
```

`TradingController` 只依赖 `ExecutionClient`。不知道下面是 Mock 还是 Hyperliquid。

`HUMMINGBOT_LIVE_CONNECTOR=true` 在 PHASE 3 **直接拒绝实例化**（即使 import 成功）。默认 Hyperliquid 模式仍用 `FakeConnector`。

## 5. RPC 契约

新增：`POST /rpc/configure`；`/health` 增加 `ready` / `worker_state` / `execution_enabled` / `sync_status`。  
测试钩子：`/rpc/test/ws_disconnect`、`/rpc/test/rest_resync`。  
`set_leverage` / 真实 `place` 在 `EXECUTION_ENABLED=false` 时不调用 connector。

错误 symbol 与 NOT_READY 返回 **REJECTED 业务体**（HTTP 200），避免 Controller 把未发送的请求标成 UNKNOWN。

## 6. 状态模型

Worker 内部标准模型（Backend 不依赖 Hummingbot 对象）：

- `ExchangePosition` / `ExchangeOrder` / `ExchangeFill` / `ExchangeAccount` / `ExchangeEvent`
- `InstrumentMeta`（szDecimals、tick、min notional）

映射层：`app/mapping.py`（Hummingbot/HL 形状 → 内部模型）。

## 7. One-way Position Mode

只允许 FLAT / LONG / SHORT。`szi` 符号映射。同一 symbol 同时 LONG+SHORT → `OneWayError` → Worker `RECOVERING`，禁止开仓。HEDGE type 记入原因。

## 8. 单币种限制

`WorkerConfig.trading_pair`（默认 `BTC-USD`）。RPC `symbol != configured` → REJECTED。不执行任意币种。`POST /rpc/configure` 与 Backend `start()` 同步交易对。

## 9. quantity / price quantization

`normalize_order_request()`：

- 数量 **向下** 对齐 step，从不静默加大
- 价格：5 位有效数字（Decimal，对应 v2.16.0 `.5g`）+ tick `ROUND_HALF_UP`
- `qty<=0` / 低于 `min_order_size` / 名义 `< 10` → **拒绝**，不改成默认数量

## 10. reduce-only

CLOSE 必须 `reduce_only=true`。

- LONG close → SELL reduce-only
- SHORT close → BUY reduce-only
- FLAT 无 close side（测试拒绝 `close_side_for_position("FLAT")`）

Adapter 不根据信号反手。Controller 仍禁止自动反手。

## 11. leverage 接口

`set_leverage(symbol, leverage)` 存在。默认 **不自动改交易所杠杆**。`configure` 只记录 expected leverage；快照杠杆不一致设 `leverage_mismatch`。`EXECUTION_ENABLED=false` 时 `set_leverage` 抛 `ExecutionDisabled`。

Controller 本阶段 **不调用** `set_leverage`（接口预留）。

## 12. UNKNOWN

规则未改：`place_order` 异常 → UNKNOWN → `get_order`+`get_fills`+`get_position` → 不重发。  
Adapter 对已提交 cloid 再次 `place` **不增加** `connector.place_calls`。

## 13. Worker Recovery

`WorkerState`: `NOT_READY` / `RECOVERING` / `READY` / `DEGRADED`。  
`is_ready()` 为假时 Position Guard 视为未连接，禁止开仓。  
`start()`：进程可达 → `connect` → `configure` → 若仍非 READY 则进入 RECOVERY。  
WS 断线：`DEGRADED`；`rest_resync` 后以 REST 为准。

## 14. REST + WS

`ExchangeStateStore`：REST snapshot + WS 增量。WS 掉线 → `RESYNC`。冲突（REST LONG vs WS SHORT）**不静默覆盖**，`CONFLICT` + `needs_reconciliation`。

## 15. reconciliation

测试覆盖：REST FLAT → WS OPEN → WS 持仓 LONG；WS 断线后 REST LONG 一致。REST 与 WS 方向冲突保持 REST 侧并标记对账。

外币种持仓：`foreign_symbols` → RECOVERING；Backend Guard `has_foreign_positions` 仍禁止开仓且不自动平仓。

## 16. 测试结果

### 本机 Python 3.14.5

```
backend> python -m pytest tests -q     → 39 passed
execution-worker> python -m pytest tests -q → 22 passed
frontend> npm run build                 → VERIFIED
```

含 PHASE 2 安全矩阵 + 本次：量化/IOC 方向/映射/One-way/单币种/DRY_RUN/cloid 不重发/WS 冲突/外币种/worker not READY。

真实 HTTP worker 集成（Mock 进程）仍由 `test_http_worker.py` **VERIFIED**。

### Python 3.12 / Docker 内 pytest

**NOT VERIFIED。**

## 17. 安全调用图

唯一业务下单路径：

```
UI/API /api/trading/* 
  → TradingController._submit
    → HttpExecutionClient.place_order
      → Worker POST /rpc/place_order
        → WorkerRuntime.place_order（symbol + READY）
          → MockExecutionAdapter.place_order
          或 HyperliquidExecutionAdapter.place_order
            →（仅 EXECUTION_ENABLED）ConnectorBridge.place(our cloid)
              → 未来 HyperliquidPerpetualDerivative._place_order
```

审查结论：

| 路径 | 结果 |
| --- | --- |
| Strategy → execution | 无 |
| API 直打 Worker | 无 |
| Frontend → Worker `:8001` / `/rpc` | 无 |
| RecoveryManager → place_order | 无 |
| Worker 自动补单 / 自动反手 | 无 |
| Connector 绕过 Adapter | 无；且 live connector 实例化被禁用 |
| `buy()`/`sell()` 隐藏重试 | Adapter 不调用这两方法 |
| 第二条交易路径 | 未发现 |

`set_leverage` / `cancel_order` 同样只经 Controller → ExecutionClient → Worker（杠杆本阶段不自动调用）。

## 18. VERIFIED

- v2.16.0 连接器源码阅读（随后删除本地副本）
- Mock 全量 PHASE 2 回归（backend 39 / worker 既有 mock 测试）
- Hyperliquid Adapter 映射 / DRY_RUN / 量化 / IOC 方向 / One-way / 单币种 / 不重发 cloid（单测）
- Worker READY 门禁（backend `is_ready` + worker runtime）
- 本机 frontend build
- 默认 `EXECUTION_ENABLED=false`

## 19. NOT VERIFIED

- 本机安装/import Hummingbot v2.16.0 包
- Docker Compose build/up / 容器内 Python 3.12
- 连接器在 Clock/Client 外独立跑通
- `cancel`+cloid 是否等于官方 `cancelByCloid`（运行时）
- 重复 cloid 在真实 HL 上的拒绝字符串
- 浏览器 E2E

## 20. N/A

- **REAL ORDER EXECUTION**
- 主网 / testnet 真实订单、真实 API Key、真实钱包
- 完整 Strategy Runtime、指标、AI、K 线、回测
- 多币种 / 多账户 / 多策略

## 21. 已知限制

- Windows 本机 Python 3.14 不能作为 Hummingbot 运行时；连接器目标仍是 Worker 内 Python 3.12（容器未验证）。
- Hyperliquid 模式默认 `FakeConnector`；不是交易所验证。
- Connector `buy()`/`sell()` 不可用作幂等 API；未来 live 接入必须继续注入我方 cloid。
- 杠杆不会在启动时自动 `updateLeverage`。
- Docker Hub 若仍失败，Compose 实际运行仍未验证（环境限制，非本阶段改镜像源）。

## 22. Git commit

工作树排除 `.env` 实值、密钥、SQLite、`node_modules`、下载的 Hummingbot 源码副本。

提交说明：`PHASE 3: execution worker hyperliquid adapter foundation`

**停止。不进入 PHASE 4。不接主网。不发真实订单。**
