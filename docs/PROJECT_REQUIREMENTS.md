# 项目需求

本文整理当前已确认的全部需求。未在本文出现的能力视为未确认，实现前必须先更新本文。

**产品：** 基于 Hummingbot + Hyperliquid 的单策略自动合约交易系统。  
**当前阶段：** PHASE 0 仅建立安全开发基础。核心业务尚未实现。

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

- Web UI。
- SQLite 持久化。
- Docker Compose 部署。
- 支持 Windows / macOS / Linux。
- 策略文件上传与版本管理。
- 策略参数可启用 / 关闭。
- 所有设置永久保存。
- 重启或故障后自动恢复（先对账，再按持久化状态继续；不自动开新仓）。

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

## 6. 非目标（当前明确不做）

- 多账户、多策略并行、多币种同时交易。
- 策略直接调用交易所。
- 自动反手 / 对冲 / 同时双向持仓。
- 在 PHASE 0 实现核心交易、UI、数据库 schema、Docker 编排或 Hummingbot 集成。

## 7. 后续实现时的已知约束（供设计，不在本 Phase 实现）

- Hummingbot 永续连接器 ID：`hyperliquid_perpetual`；testnet：`hyperliquid_perpetual_testnet`。
- Hummingbot 文档载明 Hyperliquid perp 持仓模式为 **One-way**，与“最多一个持仓”一致。
- Windows 上官方推荐 Hummingbot 走 **Docker Desktop + WSL2**，或 WSL2 内源码安装。
- 主网与 testnet 必须严格隔离；默认不得使用主网。

## 8. 需求来源

来自项目发起说明（PHASE 0 任务书）。若后续 Phase 增补需求，必须先改本文件再写代码。
