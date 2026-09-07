# newhbot

基于 Hummingbot + Hyperliquid 的单策略自动合约交易系统。

当前本地验证基线已推进至 **PHASE 149**：策略上传与受限运行时、Recovery 安全状态机、Mock 执行层（含合成 K 线）、Docker Compose 控制面、浏览器控制流、平仓确认、健康状态、SQLite 备份、执行路径架构不变量、参数运行时传递、WebSocket 重连、控制 token 运行时注入、Worker 跨平台声明、最新 Web UI 导航、订单/成交/事件表格、运行中交易设置与策略管理门禁、控制路径安全审计、密钥与默认部署安全审计、只读实时预检、受控 Hyperliquid 撤单 seam、主网/testnet 显式域隔离、实际 testnet 认证只读端到端验证、真实 testnet openOrders 开仓前预检、真实 armed 开仓 heartbeat 门禁、受控杠杆配置 seam、armed heartbeat 安全门禁、armed 订单生命周期跟踪、订单生命周期静态安全复核、Runtime 杠杆安全门禁、本地 armed 交易生命周期闭环、策略在 STOPPED/RECOVERY 下的开仓与平仓门禁及一次性执行脚本 testnet 确认门禁均已完成回归验证。仓库默认执行层仍为 **Mock**；实时连接和交易只会通过显式的本地 override 启用，运行中的密钥、数据库、日志和交易状态不随 Git 提交。

- 开发规则：`AGENTS.md`
- 需求：`docs/PROJECT_REQUIREMENTS.md`
- 架构：`docs/ARCHITECTURE.md`
- 跨电脑部署与交接：`docs/REDEPLOYMENT_GUIDE.md`
- 最新阶段报告：`docs/PHASE_143_REPORT.md`

```
docker compose up -d
```

Windows 开发也可在仓库根目录分别启动 backend / execution-worker / frontend。交易设置存在 SQLite（`./data`），不在 `.env`。正式本地栈当前应保持 `STOPPED`、交易开关关闭、持仓 `FLAT/0`；执行 Worker 镜像重建若遇 Docker Hub 网络超时，不能用修改基础镜像或配置的方式绕过。

Execution Worker 使用官方 Hummingbot `linux/amd64` 镜像；在 Apple Silicon 上由 Docker Desktop 通过显式 `platform: linux/amd64` 仿真运行，避免隐式选择错误架构。

未经确认不得连接 Hyperliquid 主网或发送真实订单。
