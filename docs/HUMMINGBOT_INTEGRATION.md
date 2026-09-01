# Hummingbot 集成研究

研究锚点：**Hummingbot v2.16.0**（GitHub tag `v2.16.0`，2026-07-29）。连接器源码按该 tag 阅读，不是 1.x。

## 1. 官方组件实际是什么

| 组件 | 官方定位（v2 文档） | 会不会下单 | 是否适合本项目策略层 |
| --- | --- | --- | --- |
| Connector `hyperliquid_perpetual` | 交易所适配 | 是（执行） | **只作为执行层复用** |
| Script / `StrategyV2Base` | 长驻策略；用 Executor 下单，不再推荐裸 `buy()/sell()` | 是 | 否：策略与执行耦合 |
| Controller | 生产级子策略；由 `v2_with_controllers.py` 加载，**可多策略并行** | 通过 ExecutorAction 下单 | 否：违背「策略只出信号」 |
| Executor（尤其 `PositionExecutor`） | 有限生命周期：开仓、刷新、止盈止损、平仓 | 是，且自管 TP/SL | 否：本项目要求策略自己负责止盈止损 |
| hummingbot-api | FastAPI + **PostgreSQL** + **EMQX** + Docker 编排多 bot；可直连交易所或拉起 bot | 是 | 否：过重、多账户/多 bot、攻击面大 |

文档：

- https://hummingbot.org/strategies/v2-strategies/
- https://hummingbot.org/strategies/v2-strategies/controllers/
- https://hummingbot.org/strategies/v2-strategies/executors/
- https://hummingbot.org/hummingbot-api/
- https://hummingbot.org/exchanges/hyperliquid/

源码（已读 v2.16.0）：

- `hummingbot/connector/derivative/hyperliquid_perpetual/hyperliquid_perpetual_derivative.py`
- `hummingbot/connector/derivative/hyperliquid_perpetual/hyperliquid_perpetual_constants.py`
- `hummingbot/strategy_v2/controllers/directional_trading_controller_base.py`
- `hummingbot/strategy_v2/executors/position_executor/data_types.py`
- `https://github.com/hummingbot/hummingbot-api` `docker-compose.yml`（main）

## 2. 为什么不能把策略放进 Hummingbot Controller

`DirectionalTradingControllerBase`（v2.16.0）默认行为：

- `processed_data["signal"] != 0` 且 `can_create_executor` 时 **直接** `CreateExecutorAction(PositionExecutorConfig)`。
- `max_executors_per_side` 默认 **2**。
- `position_mode` 默认 **HEDGE**；Hyperliquid connector 只支持 **ONEWAY**。
- Triple Barrier（止盈/止损/超时）在 **Executor** 里，不在「纯信号」里。

这与本项目硬规则冲突：策略不得下单、永远最多一仓、禁止自动反手、止盈止损由策略发 `CLOSE`。

**结论：不需要、也不应该实现一个完整的 Hummingbot Strategy Runtime 克隆。需要的是极窄的插件运行时（输入市场数据，输出四态信号）。Hummingbot 已有机制不能满足「信号与下单分离」。**

## 3. 三种架构比较

| 维度 | A. Backend → 独立 Hummingbot 进程/API | B. Backend 进程内 import 核心模块 | C. 使用 V2 Controller/Executor 体系 | **D. 自建控制面 + Execution Worker（推荐）** |
| --- | --- | --- | --- | --- |
| 稳定性 | hummingbot-api 依赖 Postgres/EMQX/docker.sock，故障面大；纯 client 进程则 MQTT 复杂 | UI/策略崩溃会拖死连接器 | Executor 超时/多 executor 与「一仓」冲突（v2.16.0 刚修过 shutdown 持仓） | 控制面与执行面隔离；Worker 崩溃只进 Recovery |
| 可维护性 | 跟上游 API 大而全的路由 | 与 Cython/Clock 强耦合，升级痛 | 必须改上游 Controller 语义 | 只跟踪 connector 与 HL API |
| 开发难度 | 高（先吃懂别人的多 bot 平台） | 中高（Windows 3.14 无法编 HB） | 表面快、语义不合 | 中：自写 Guard/Recovery，执行复用 connector |
| 交易延迟 | 多一跳 MQTT/HTTP | 最低 | 低，但 Executor 内部还有刷新逻辑 | 本机 RPC，足够非 HFT |
| 状态一致性 | 三份状态（我们 / API DB / 交易所） | 两份 | Executor 状态 vs 交易所 | 交易所为准 + 我方 SQLite 审计 |
| 重启恢复 | 官方 bot 目录有 sqlite，但是另一套 | 同进程，更难沙箱 | Executor 持久化不按我们的 UNKNOWN/cloid 模型 | 由我们的 Recovery 状态机拥有 |
| Docker | 官方就是 Compose，但含 Postgres/EMQX | 本机 Python，Windows 不官方 | 官方 bot 容器 | 两容器即可 |
| HB 升级 | 被 API/MQTT 协议绑住 | 每次改 import | 策略文件格式绑死 | 只回归 connector |
| HL 兼容 | 取决于他们何时升 connector | 同左 | 同左 | 钉死 v2.16.0 connector，按需升级 |
| API 可控性 | 暴露大量交易路由，官方警告勿公网 | 我们自己控 | 策略一加载就会下单 | Worker 只开放 4～5 个内部方法 |
| 测试 | 要 mock 整套 API | 可单测 connector 包装 | 难测「禁止下单的策略」 | 策略单测纯函数；Guard 单测表驱动 |
| 未来扩展 | 多 bot 是他们的目标，不是我们的 | 容易把禁令做漏 | 鼓励多策略 | 保持单策略；远程访问只加认证 |

### 为什么选 D 而不是 A

A 若指 **hummingbot-api**：官方 Compose 含 PostgreSQL 16、EMQX 5、把 **docker.sock** 挂进 API 以拉起更多 bot。这是给 Condor/多交易所仪表盘用的。本项目单账户单策略，引入 MQTT 与第二套订单库会破坏「交易所优先 + 我方 SQLite 审计」。官方还把 MCP/AI 接在同一 API 上，增大误下单面。

A 若指 **单独跑 Hummingbot client + 我们用 CLI/MQTT 遥控**：仍要把策略放进 HB 才能转，或只用 client 当下单 daemon。后者接近 D，但官方 client 不是为「无策略、只接受外部 place/cancel」设计的，包袱更大。

### 为什么选 D 而不是 B

B 把 connector 嵌进 FastAPI 同进程：延迟好，但 (1) 官方 Windows 路径是 WSL2/Docker，本机 Python 3.14 不能当 HB 运行时；(2) 策略沙箱与执行共享解释器，恶意 `strategy.py` 更容易摸到密钥；(3) UI 死循环/OOM 会打断订单回报。

D 把 connector 放到 **Linux Execution Worker**，Backend 可以是同 Compose 里的 app 容器（生产）或开发机上的 Node/Python（仅 UI 开发、禁止实盘）。

### 为什么选 D 而不是 C

C 是 Hummingbot 自己的「正确用法」，但是给 **多策略、Executor 自管仓位** 的人用的。本项目硬性禁止策略下单、禁止自动反手、要求策略发 `CLOSE` 做止盈止损。用 C 等于一上来就违反 `AGENTS.md`。

## 4. 连接器里已验证、对本项目有用的事实

来源：`hyperliquid_perpetual_derivative.py` / `*_constants.py` @ v2.16.0。

| 项 | 源码结论 |
| --- | --- |
| 连接器 ID | `hyperliquid_perpetual`；testnet domain `hyperliquid_perpetual_testnet` |
| REST | `https://api.hyperliquid.xyz`；WS `wss://api.hyperliquid.xyz/ws` |
| 订单类型 | LIMIT=Gtc，LIMIT_MAKER=Alo，MARKET=**Ioc 限价**（不是原生 market 类型） |
| 市价滑点 | `MARKET_ORDER_SLIPPAGE = 0.05`（买 *1.05，卖 *0.95） |
| 最小名义 | `MIN_NOTIONAL_SIZE = 10`（与 HL `MinTradeNtl` $10 一致） |
| 持仓模式 | `supported_position_modes → [ONEWAY]`；设置 HEDGE 会失败 |
| 平仓 | `reduceOnly: position_action == PositionAction.CLOSE` |
| cloid | `buy()`/`sell()` 生成 HBOT 前缀 id，再 **MD5 成 `0x`+32 hex** 作为 cloid |
| 撤单 | 内部 `type: cancel` 且带 `cloid`（是否等于官方 `cancelByCloid`：**PHASE 2 必须对照实测**） |
| 杠杆 | `updateLeverage`；默认 `isCross=True`；HIP-3 走 isolated |
| 价格量化 | 最多 5 位有效数字 + tick（v2.16.0 #8356 修复） |
| 数量步长 | `10 ** -szDecimals` |
| 持仓同步 | `clearinghouseState`；`szi>0` LONG，`<0` SHORT；关闭的仓会从列表消失，源码会清本地缓存 |
| 用户流 | `orderUpdates` + `user` |
| Builder | 主网非 vault 注入 Foundation builder；testnet/vault 省略 |
| 认证 | `arb_wallet` 或 `api_wallet` |
| 限速 | 1200 / 60s（连接器侧） |

**风险：** 每次调用 `buy()`/`sell()` 都会 **新生成** cloid。网络超时后如果再次调用，会变成第二张单。Execution Adapter **必须**在调用前写入并复用我们自己的 cloid，不能直接当幂等 API 用。能否不改 fork 就传入自定义 cloid：源码显示要走 `_create_order` / 子类覆盖 `buy`/`sell`。**未在运行时验证，PHASE 2 做 POC。**

## 5. Execution Worker 形态

推荐：Compose 服务 `execution`，镜像基于官方 `hummingbot/hummingbot:version-2.16.0`（已有 **linux/amd64 与 linux/arm64**），进程只启动连接器 + 极窄 RPC。

不推荐：在 Worker 里 `start --script v2_with_controllers`。

备选（仅当 POC 证明 connector 离开 Clock/Client 无法独立运行）：用官方 client 跑一个 **空脚本**，我们通过内部 socket 调其 connector。仍禁止加载用户策略进该进程。

## 6. 市场数据

策略需要价格/K 线，但 UI 不画 K 线。

- 执行与持仓：必须走已认证用户流 / `clearinghouseState`。
- 策略用 K 线：可用 Hummingbot `CandlesFactory`（`hyperliquid_perpetual`）或 HL WS `candle`。**未选定**；PHASE 2 POC 比较延迟与稳定性。
- 不得让策略自己访问公网。
