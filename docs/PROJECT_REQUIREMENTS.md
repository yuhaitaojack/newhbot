# 项目需求

本文整理当前已确认的全部需求。未在本文出现的能力视为未确认，实现前必须先更新本文。

**产品：** 基于 Hummingbot + Hyperliquid 的单策略自动合约交易系统。  
**当前阶段：** 本地安全验证基线已推进至 PHASE 132。控制面、Mock 执行层、策略运行时、Recovery 状态机、持久化、受控撤单与杠杆配置 seam、armed 订单生命周期跟踪与 Runtime 杠杆安全门禁、本地 armed 生命周期闭环、真实 testnet openOrders 开仓前预检、真实 armed 开仓 heartbeat 门禁、主网/testnet 显式域隔离、testnet 认证只读、一次性执行脚本 testnet 确认门禁及 armed heartbeat 安全门禁与 Docker Compose 已实现并完成回归；默认仍关闭真实执行，未连接 Hyperliquid 主网。

## 1. 交易范围

| 项 | 要求 |
| --- | --- |
| 市场 | Hyperliquid 永续合约 |
| 执行层 | Hummingbot |
| 账户 | 单账户 |
| 策略 | 单策略 |
| 交易品种 | 单交易币种 |
| 持仓 | 永远最多一个实际持仓 |
| 反手 | 无自动反手 |
| 策略输出 | 只允许 `LONG` / `SHORT` / `CLOSE` / `HOLD` |

## 2. 架构原则

- 策略是信号层，不是执行层。策略不得直接下单。
- 所有交易执行必须经过 Trading Controller，禁止旁路。
- 有持仓时禁止新的 `LONG` / `SHORT` 开仓；只允许 `HOLD` 或 `CLOSE`。
- 禁止把反向信号当成自动反手（先平后开必须是两次独立、受控的动作，且平仓完成后才允许新开仓）。
- Hyperliquid 交易所真实状态优先于本地 SQLite / 内存状态。
- 启动、崩溃、状态不一致时进入 Recovery；Recovery 期间禁止开仓。
- 所有交易相关设置必须持久化，重启后仍有效。

## 3. 应用能力

- Web UI：状态、交易记录、控制、配置。不做 K 线；K 线由用户在 TradingView 查看。
- SQLite 持久化（PHASE 1 结论：PostgreSQL 不必要）。
- 生产部署推荐 Docker Compose；Windows / macOS / Linux 均可部署；Apple Silicon (ARM64) 作为目标之一。
- 策略文件上传与版本管理（`strategy.py` + `manifest.yaml`）。
- 策略参数可启用 / 关闭：关闭用策略默认值，开启用数据库用户配置。
- 策略本身负责止盈止损逻辑；平仓只能由策略 `CLOSE` 或人工平仓触发。
- 所有设置永久保存。
- 重启或故障后自动恢复（先对账，再按持久化状态继续；Recovery 禁止开新仓）。
- 架构须预留远程访问的认证与网络安全（默认不公网暴露）。

## 4. Web UI 控制

Web UI 必须提供：

1. 启动
2. 停止
3. 一键平仓并停止
4. 一键平仓继续运行
5. 紧急停止

控制动作必须走 Trading Controller，并写入持久化状态。

## 5. 安全与合规（开发期）

- 禁止提交真实密钥、私钥、API secret、助记词。
- 禁止未经用户明确确认进行真实交易或连接 Hyperliquid 主网。
- PHASE 0 及未获授权的后续工作：不连接真实 Hyperliquid，不执行真实交易。
- 不允许通过修改测试来掩盖代码问题。
- 每个 Phase 完成必须生成报告并停止，不得擅自进入下一 Phase。

## 6. 历史 PHASE 0/PHASE 1 非目标

以下内容记录的是 PHASE 0/PHASE 1 研究阶段的非目标，不代表当前实现仍未完成；真实主网执行仍受 `AGENTS.md` 和当前会话明确确认约束。

- 多账户、多策略并行、多币种同时交易。
- 策略直接调用交易所。
- 自动反手 / 对冲 / 同时双向持仓。
- 在 PHASE 0 / PHASE 1 实现核心交易、UI、数据库 schema、Docker 编排或 Hummingbot 集成。
- K 线 UI、回测系统、高频交易、AI 交易、多微服务、Kubernetes、Redis、Kafka。
- 采用 Hummingbot Strategy V2 Controller / PositionExecutor 作为策略决策层（它们会自己下单并自管止盈止损）。
- 采用 hummingbot-api 全家桶（PostgreSQL + EMQX + Docker-in-Docker 多 bot）作为本项目后端。

## 7. 后续实现时的已知约束（供设计，不在本 Phase 实现）

- Hummingbot 永续连接器 ID：`hyperliquid_perpetual`；testnet：`hyperliquid_perpetual_testnet`。
- Hummingbot 文档载明 Hyperliquid perp 持仓模式为 **One-way**，与“最多一个持仓”一致。
- Windows 上官方推荐 Hummingbot 走 **Docker Desktop + WSL2**，或 WSL2 内源码安装。
- 主网与 testnet 必须严格隔离；默认不得使用主网。

## 8. PHASE 1 增补的执行约束

- 开仓前必须再次查询 Hyperliquid 真实持仓。
- 订单状态不确定（UNKNOWN）时禁止重复下单。
- 真正下单只允许 Trading Controller → Execution Worker；策略进程禁止接触 connector。
- 推荐架构见 `docs/ARCHITECTURE.md`（方案 D）。

## 9. 需求来源

PHASE 0 任务书 + PHASE 1 架构研究确认项。若后续 Phase 增补需求，必须先改本文件再写代码。
