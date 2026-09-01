# 系统架构

本文是 PHASE 1 的架构结论。不实现代码。安全规则以 `AGENTS.md` 为准。

## 1. 推荐方案：方案 D

**自建控制面 + 独立 Execution Worker，只复用 Hummingbot 的 Hyperliquid 永续连接器，不复用 Strategy V2 Controller / Executor，不采用 hummingbot-api 全家桶。**

```
Web UI (SPA)
    │  REST + WebSocket（认证后）
    ▼
Trading Service / API  ──────── SQLite (WAL)
    │
    ├─ Strategy Plugin Runtime（独立进程，只出信号）
    ├─ Trading Controller（唯一下单决策）
    ├─ Position Guard（单持仓锁）
    ├─ Recovery Manager（状态机）
    ├─ Audit / System Events
    │
    │  窄接口 RPC（place / cancel / query / stream）
    ▼
Execution Worker（Linux 容器）
    └─ Hummingbot `hyperliquid_perpetual` connector
            ▼
      Hyperliquid REST + WebSocket
```

方案 A/B/C 的否决理由见 `docs/HUMMINGBOT_INTEGRATION.md` 与 `docs/PHASE_1_REPORT.md`。

## 2. 模块职责

| 模块 | 职责 | 禁止 |
| --- | --- | --- |
| Web UI | Dashboard、策略版本、参数开关、设置、订单/成交/持仓、系统事件、审计；启动/停止/平仓并停止/平仓并继续/紧急停止 | 直连交易所；画 K 线 |
| API | 认证、REST 命令、WebSocket 推送、上传策略、读写 SQLite | 自己下单 |
| Trading Service | 把 UI 命令与策略信号编排进 Controller | 绕过 Guard |
| Trading Controller | 解释 `LONG/SHORT/CLOSE/HOLD` 与人工命令；调用 Execution Worker | 自动反手；Recovery 开仓；UNKNOWN 时重发 |
| Position Guard | 开仓门闩：本地 FLAT **且** 交易所 FLAT **且** 无 UNKNOWN 订单 **且** 非 Recovery | 用本地状态覆盖交易所 |
| Strategy Runtime | 加载一个已启用策略版本；输入市场数据；输出一个 Signal | import 网络/下单/Hummingbot；改杠杆 |
| Execution Worker | 签名、量化、下单、撤单、查仓、用户流 | 策略逻辑；多币种；自作主张补单 |
| SQLite | 设置、策略版本、参数、信号、订单、成交、持仓快照、事件、审计 | 作为仓位真相源 |
| Recovery | 启动与故障后的对账状态机 | 对账未完成时开仓 |

## 3. 数据流

### 3.1 开仓（LONG 或 SHORT）

1. Runtime 产出 `LONG` 或 `SHORT`。
2. Controller 拒绝：已有仓、有未完成开仓单、Recovery、ERROR、断连。
3. Guard 再查 Hyperliquid `clearinghouseState` + `openOrders`。仅当两边都 FLAT 才放行。
4. Controller **先**把意图写入 SQLite（`orders.status=UNKNOWN`，带确定性 `cloid`），**再**调用 Worker。
5. Worker 用该 `cloid` 下单（reduceOnly=false）。
6. 以交易所回报 / REST `orderStatus` 更新本地。成交后本地仓位跟随交易所。

### 3.2 平仓

只接受：策略 `CLOSE`，或 UI「平仓并停止 / 平仓并继续 / 紧急停止」中的平仓部分。

1. Guard 确认交易所有仓。
2. 先撤该币种非 reduce-only 挂单。
3. 用 reduce-only 市价（Hummingbot 实现为 IOC 限价 + 滑点）平仓。
4. 再次查询 `clearinghouseState`，确认 `szi==0`。
5. 禁止在同一次循环里根据反向信号立即开仓。

### 3.3 止盈止损

策略内部计算。触发时只发 `CLOSE`。不使用 Hummingbot `PositionExecutor` Triple Barrier，也不默认挂 Hyperliquid `positionTpsl` 组。交易所原生 TP/SL **未作为本阶段选定机制**（见未决问题）。

### 3.4 实时状态

- Execution Worker 订阅 Hyperliquid WS：`orderUpdates`、`userFills`、`clearinghouseState`、`openOrders`。
- Backend 聚合后经 **WebSocket** 推给 UI。
- UI 断线：重连后走 REST snapshot，再接增量。不假设没收到的推送可以忽略。

## 4. 单币种 / 单持仓

- `settings.trading_pair` 全局唯一。Worker 只订阅这一对。
- 账户上若出现**其他币种持仓**（人工在网页开的仓）：进入 Recovery，禁止开仓，UI 告警，需人工处理。这不是自动平掉别人的仓。
- Hyperliquid perp 持仓类型为 `oneWay`；Hummingbot connector `supported_position_modes = [ONEWAY]`。

## 5. 认证与远程访问

当前是单用户个人系统，但架构预留：

- API 默认绑定 `127.0.0.1`。
- 会话认证（后续可加密码 / 可选 Tailscale）。不引入 hummingbot-api 的 MCP。
- 不把 Docker sock 挂进容器。
- 密钥只在 Execution Worker 环境变量 / Docker secret，不进 Git，不进 SQLite 明文（至少加密）。

## 6. 明确不采用

Kubernetes、Redis、Kafka、PostgreSQL、Hummingbot Dashboard/Condor/MCP、多 bot、回测服务、K 线组件。
