# PHASE 1 报告：Hummingbot + Hyperliquid 架构研究

**状态：** 完成并停止。未实现核心业务代码，未连接 Hyperliquid，未执行真实交易。  
**日期：** 2026-09-01  
**Hummingbot 版本锚点：** **v2.16.0**（GitHub tag，发布 2026-07-29）  
**推荐架构：** 方案 D（自建控制面 + Execution Worker，只复用 Hyperliquid 永续连接器）

详细设计拆在：

- `docs/ARCHITECTURE.md`
- `docs/HUMMINGBOT_INTEGRATION.md`
- `docs/TRADING_STATE_MACHINE.md`
- `docs/EXECUTION_DESIGN.md`
- `docs/RECOVERY_DESIGN.md`
- `docs/DEPLOYMENT.md`
- `docs/DATA_AND_UI.md`
- `docs/STRATEGY_UPLOAD_SECURITY.md`

## 1. 研究过的官方资料

| URL | 内容 | 对本项目 | 版本 | 源码验证 |
| --- | --- | --- | --- | --- |
| https://github.com/hummingbot/hummingbot/releases/tag/v2.16.0 | 当前稳定版；含 HL 价格量化修复 #8356 | 钉死执行层版本 | v2.16.0 | 是（release 页） |
| https://hummingbot.org/release-notes/2.16.0/ | 同上；API/Condor 为持续部署 | 不要把 hummingbot-api 当有 tag 的稳定面 | 2026-07-29 | 文档 |
| https://hummingbot.org/exchanges/hyperliquid/ | perp 连接器、testnet、One-way、订单类型 | 执行层边界 | 文档现时 | 连接器源码交叉 |
| https://hummingbot.org/strategies/v2-strategies/ | Script / Controller / Executor 分工 | **不能**用 Controller 当策略层 | 现时文档 | 是 |
| https://hummingbot.org/strategies/v2-strategies/controllers/ | Controller 为多策略并行设计 | 与单策略冲突 | 现时 | 是 |
| https://hummingbot.org/strategies/v2-strategies/executors/ | Executor 自己管单；API 可直接建 Executor | PositionExecutor 会管 TP/SL | 现时 | data_types 已读 |
| https://hummingbot.org/hummingbot-api/ | FastAPI+Postgres+EMQX+多 bot | 否决作本项目后端 | 文档称 API v1.0.1 | Compose 已读 |
| https://hummingbot.org/hummingbot-api/installation/ | Docker 安装、Tailscale、Python 3.12+ | 过重 | 现时 | 文档 |
| https://hummingbot.org/client/installation/ | Win=WSL2+Docker；镜像 amd64/arm64 | 部署 | 现时 | Hub tag 交叉 |
| https://hub.docker.com/r/hummingbot/hummingbot/tags?name=version-2.16.0 | linux/amd64 + **linux/arm64** | Apple Silicon 可部署 | version-2.16.0 | Hub 页 |
| https://github.com/hummingbot/hummingbot/tree/v2.16.0/hummingbot/connector/derivative/hyperliquid_perpetual | 连接器文件列表 | 执行实现 | v2.16.0 | 是 |
| 同上 `hyperliquid_perpetual_derivative.py` | 下单、cloid MD5、reduceOnly、ONEWAY、杠杆 | 幂等风险、量化 | v2.16.0 | **是** |
| 同上 `hyperliquid_perpetual_constants.py` | URL、MIN_NOTIONAL=10、滑点 0.05、订单状态映射 | 执行参数 | v2.16.0 | **是** |
| `directional_trading_controller_base.py` | signal→CreateExecutor；max_executors=2；默认 HEDGE | 否决 C | v2.16.0 | **是** |
| `position_executor/data_types.py` | TripleBarrier TP/SL | 与「策略负责止盈止损」冲突 | v2.16.0 | **是** |
| https://raw.githubusercontent.com/hummingbot/hummingbot-api/main/docker-compose.yml | postgres+emqx+docker.sock | 否决方案 A 全家桶 | main（无本仓库 tag） | **是** |
| https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint | order/cancel/leverage；cloid 字段 | 执行 | 现时官方 | 文档 |
| https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint | orderStatus(oid **或** cloid)、openOrders | UNKNOWN 查询 | 现时 | 文档 |
| https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals | clearinghouseState；assetPositions type oneWay | 仓位真相 | 现时 | 文档 |
| https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket | 主网/testnet WS；必须处理服务端断开 | 重连 | 现时 | 文档 |
| https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions | orderUpdates、userFills、clearinghouseState、openOrders、candle | 订阅清单 | 现时 | 文档 |
| https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets | nonce 唯一；查询用 master 地址不是 agent | 防重放、密钥模型 | 现时 | 文档 |
| https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses | MinTradeNtl $10、ReduceOnly、IocCancel 等 | 失败分类 | 现时 | 文档 |

第三方（仅作线索，**不以之为最终依据**）：Chainstack 称「重复 cloid 会被拒」。官方 gitbook 已定义 cloid 格式与 `orderStatus` 可用 cloid，但 **未在已读页面写明重复 cloid 的精确错误串**。见第 18 节。

## 2. Hummingbot 版本

- **稳定 Client：** v2.16.0（2026-07-29）。Docker：`hummingbot/hummingbot:version-2.16.0`。
- **不要**用 1.x 的 StrategyBase 设计本系统。V2 官方入口是 Script(`StrategyV2Base`) / Controller / Executor。
- **hummingbot-api** 官方写明与 Condor 一样 **持续部署、无与 Client 同步的固定 release**。不能把它当「v2.16.0 配套 API」。
- 连接器相关本版本修复：Hyperliquid perp **价格量化对齐 tick**（#8356）。执行层应钉 v2.16.0 或更新且含该修复的 tag。

## 3. Hyperliquid 接口结论

已确认（文档 ± 连接器源码）：

- 永续仓位模式 **one-way**（文档示例与 WS 类型 `AssetPosition.type = "oneWay"`；HB 只实现 ONEWAY）。
- 持仓查询：`POST /info {type:clearinghouseState,user}`；`szi` 正=多、负=空、省略=平。
- 下单：`POST /exchange` action `order`；`r` reduceOnly；可选 cloid。
- 市价在 HB 中 = IOC 限价 ±5% 滑点，不是另一套 API。
- 最小名义 **$10**。
- 杠杆 `updateLeverage`。
- 订单查询：`orderStatus` 接受 oid 或 16-byte hex cloid。
- WS 用户流：`orderUpdates`、`userFills`（先 snapshot）、`clearinghouseState`、`openOrders`。
- 服务端会无预告断开 WS，必须重连并用 snapshot/info 补洞。
- nonce 每个 signer 唯一且须在时间窗内；API wallet 只用于签名，查账户要用 **master 地址**。

未确认（见第 18 节）：重复 cloid 拒绝行为；HB `cancel`+cloid 是否等于官方 `cancelByCloid`；IOC 滑点 5% 是否可配置得更严。

## 4. Hummingbot 集成方案对比

见 `docs/HUMMINGBOT_INTEGRATION.md` 表格。摘要：

- **A** 独立 HB 进程 / hummingbot-api：状态分裂，API 全家桶过重。
- **B** 同进程 import 核心模块：Windows/3.14 不友好，策略与密钥同命运。
- **C** V2 Controller/Executor：官方正确用法，但会自己下单、默认多 executor、Executor 管 TP/SL、默认 HEDGE。

## 5. 最终推荐架构

**方案 D。** 图见第 14 节与 `docs/ARCHITECTURE.md`。

## 6. Strategy Runtime 方案

| 候选 | 结论 |
| --- | --- |
| Strategy V2 Controller | 否 |
| Script | 否（同样会下单） |
| 只用 Executor | 否（执行+TP/SL 捆在一起） |
| **自建 Strategy Plugin Runtime** | **是**：独立进程，只输出 LONG/SHORT/CLOSE/HOLD |

**是否需要自己实现完整 Strategy Runtime？需要一个，但不需要 Hummingbot 那种。** 只要：加载一个版本、喂只读市场数据、收一个信号、参数开关、崩溃隔离。市场数据管道和订单状态机都不是策略的事。

## 7. Execution 方案

Execution Worker 进程（Linux 容器）包装 `hyperliquid_perpetual` 连接器。开仓/平仓/撤单/查仓/订阅。

幂等：先把 **cloid + UNKNOWN** 写入 SQLite，再下单；超时 **只查询不换 cloid 重发**，直到 PHASE 2 证实重复 cloid 可安全重放。详见 `docs/EXECUTION_DESIGN.md`。

## 8. 单持仓安全机制

Position Guard：仅当本地 FLAT **且** 交易所 FLAT **且** 无 UNKNOWN **且** RUNNING 才允许 LONG/SHORT。有仓一律拒绝新开仓，反向信号不得解释为反手。其它币种仓位 → RECOVERY。详见 `docs/TRADING_STATE_MACHINE.md`。

锁的数据源优先级：

1. Hyperliquid `clearinghouseState` + `openOrders` + `orderStatus(cloid)`
2. Hummingbot connector 内存仓位（仅辅助）
3. SQLite orders/positions（意图与审计）

## 9. Recovery 机制

状态：STARTING → CONNECTING → SYNCING → RECONCILING → READY/RUNNING 或 RECOVERY。场景 A–M 见 `docs/RECOVERY_DESIGN.md`。

可自动回 RUNNING：对账一致、无 UNKNOWN、用户意图 running、非 estop。  
必须人工：方向冲突、多币种仓、库损坏、estop、UNKNOWN 无法解释。

平仓中崩溃：若已持久化 `close_intent=in_progress`，恢复后允许继续 reduce-only（完成原命令，不是新开仓）。

## 10. Docker 方案

比较见 `docs/DEPLOYMENT.md`。

**生产推荐 Compose 两容器：`app` + `execution`。** 钉 HB `version-2.16.0`。SQLite volume 只挂 app。不挂 docker.sock。端口绑 127.0.0.1。

Apple Silicon：官方镜像有 linux/arm64，**可以部署**（app 镜像需同样支持，PHASE 2 验证）。

本机 PHASE 0：仍无 Docker Desktop——这是下一阶段安装前置，不是架构否决。

开发期允许：只跑 UI 的原生 Backend，**禁止**在 Windows Python 3.14 上实盘。

## 11. Web UI 方案

SPA + REST 命令 + WebSocket 状态。页面：Dashboard、Strategy、Parameters、Settings、Orders、Fills、Trades、Positions、System Events、Audit。无 K 线。断线用 snapshot 再接增量。预留单用户认证；默认不公网暴露。

## 12. SQLite / PostgreSQL

**选 SQLite。** 单写者、WAL、`synchronous=FULL`、文件备份。PostgreSQL 是 hummingbot-api 多 bot 的选择，本项目用不上。

## 13. Strategy Upload 安全方案

独立进程 + 导入白名单 + 无网络 + 超时。v1 **不做** 每策略独立 Docker。安全等级：防止失误脚本碰到密钥/下单，不是多租户。详见 `docs/STRATEGY_UPLOAD_SECURITY.md`。

## 14. 完整架构图

```
                    ┌────────────┐
                    │  Web UI    │
                    │  SPA       │
                    └─────┬──────┘
                          │ REST 命令 + WS 状态（认证）
                    ┌─────▼──────┐
                    │    API     │
                    └──┬───┬──┬──┘
           ┌───────────┘   │  └───────────┐
           ▼               ▼              ▼
    Strategy Runtime  Trading Service   SQLite
    (plugin proc)          │            WAL
           │               ▼            │
           │  Signal  Trading Controller│
           │               │            │
           │               ▼            │
           │        Position Guard      │
           │               │            │
           │               ▼            │
           │        Recovery Manager────┘
           │               │
           │               │ 内部 RPC
           │         ┌─────▼──────┐
           │         │ Execution  │
           │         │ Worker     │
           │         │ HB HL perp │
           │         └─────┬──────┘
           │               │ REST+WS
           │         ┌─────▼──────┐
           └─只读行情┤ Hyperliquid│
                     └────────────┘

Audit/Events ← Controller, Guard, Recovery, API
策略文件版本 ← API 上传（不进 Worker）
密钥 ← 仅 Worker 环境
```

## 15. 数据流

开仓：Signal → Guard（再查交易所）→ INSERT UNKNOWN+cloid → Worker.place → 回报/orderStatus → 更新仓位。  
平仓：CLOSE 或人工 → 持久化 close_intent → 撤开仓单 → reduce-only → 确认 szi=0。  
UI：REST 改变意图；WS 推送只读。

## 16. 状态机

见 `docs/TRADING_STATE_MACHINE.md`。核心：RUNNING 才能开仓；RECOVERY/UNKNOWN/ERROR/断连都不能开仓；停止不平仓；紧急停止尽量平仓并锁定。

## 17. 风险清单

| ID | 风险 | 缓解 |
| --- | --- | --- |
| R1 | `buy()` 每次新 cloid，超时重试双开 | 禁用该路径；自管 cloid；超时只查 |
| R2 | 提交后崩溃且未落库 | 先 COMMIT 再发送 |
| R3 | 部分成交 | 状态 PARTIAL；平仓循环直到 FLAT 或 RECOVERY |
| R4 | IOC 滑点 5% 过大 | PHASE 2 评估可配置滑点；失败不改 GTC |
| R5 | 用户在网页开了别的币 | Guard 发现 → RECOVERY |
| R6 | 策略恶意代码 | 独立进程、白名单、无密钥 |
| R7 | 误把 API 暴露公网 | 默认 loopback；不引入 MCP |
| R8 | Windows 无 Docker | 部署前置；不在 Win 原生跑 HB |
| R9 | 钉死 HB 版本后上游修复 | 有计划升 tag，回归量化与 ONEWAY |
| R10 | Builder 字段主网行为 | 跟随连接器；testnet 无 builder |
| R11 | SQLite 损坏 | WAL+备份；损坏则人工 |

## 18. 尚未解决的问题

下列 **未确认，需要下一阶段（POC / testnet）验证**。未编造结论。

1. 重复使用同一 cloid 下单，交易所精确行为（拒 / 返回原单 / 其它）。
2. Hummingbot `cancel` 带 cloid 是否被接受，或必须 `cancelByCloid`。
3. 不启动完整 Hummingbot Client/Clock，能否稳定只跑 `HyperliquidPerpetualDerivative`。
4. 若 3 为否：空 Script 当 daemon 的最小表面。
5. 策略行情：CandlesFactory vs 直接 WS `candle` 的延迟与断线表现。
6. IOC 5% 滑点在目标币种是否可接受；能否安全改小。
7. Worker↔Backend 心跳丢失后是否自动撤开仓单的超时秒数。
8. `orderStatus` 在「请求未到达」时的返回，与「还在处理」如何区分。
9. 本机构建/拉取 `version-2.16.0` arm64/amd64 镜像（本机尚无 Docker）。
10. API wallet 与 arb wallet 两种认证在连接器里的行为差异（源码有 `hyperliquid_perpetual_mode`，未运行）。

## 19. PHASE 2 实施建议

PHASE 2 应仍 **禁止主网**，建议范围：

1. 安装 Docker Desktop + WSL2（用户确认后）。
2. POC：容器内启动连接器或最小 client，**只读** testnet `clearinghouseState`（仍须用户明确允许 testnet 密钥；若用户不允许，则只用未认证的 `metaAndAssetCtxs`）。
3. POC：自定义 cloid 注入路径（子类 vs `_create_order`）。
4. 定内部 RPC schema 与 SQLite DDL，仍不写完整 UI。
5. 单测：Guard 真值表、UNKNOWN 不重发。

不要在 PHASE 2 擅自做完整 Web UI 或实盘。

## 20. 与 PHASE 0 / AGENTS.md 的冲突检查

无冲突。PHASE 1 提示词把 Docker 降为「候选」；研究后 **生产仍推荐 Compose**，与 PHASE 0 需求一致，并写明原生 Windows 不能当执行层。

新增已写入 `docs/PROJECT_REQUIREMENTS.md`：无 K 线、策略管止盈止损、参数开关语义、预留认证、否决 V2 Controller 与 hummingbot-api 全家桶。

## 21. 为什么选择方案 D，而不是 A 或 C（也不是 B）

**不是 A：** hummingbot-api 是多 bot 交易中台（Postgres、EMQX、docker.sock、MCP）。我们需要的是单账户单策略的窄控制面。把订单真相放进别人的 Postgres 会违反「Hyperliquid 优先 + 我方 SQLite 审计」。独立 HB client 当黑盒进程则缺少「只接受外部 cloid 下单」的官方接口。

**不是 C：** V2 Controller 在源码里就是「算信号并且 CreateExecutor」。PositionExecutor 拥有 Triple Barrier。默认最多每边 2 个 executor、默认 HEDGE。采用 C 等于让策略下单，直接违反 `AGENTS.md`。

**不是 B：** 同进程嵌入在 Windows/Python 3.14 上不可作为生产执行层，且用户策略与密钥同解释器。

**是 D：** 把 Hummingbot **真正有价值的部分**（已维护的 Hyperliquid 永续连接器：签名、量化、WS、reduceOnly、ONEWAY）留在 Linux Worker；把本项目真正有价值的部分（四态信号、Position Guard、UNKNOWN 幂等、Recovery、SQLite、Web 控制面）留在我们手里。

## 22. 停止

PHASE 1 已完成。不进入 PHASE 2。
