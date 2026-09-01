# newhbot

基于 Hummingbot + Hyperliquid 的单策略自动合约交易系统。

当前处于 **PHASE 2**：基础项目架构、Docker、数据库与进程边界。执行层为 **Mock**，**未连接真实 Hyperliquid**，**未发送真实订单**。

- 开发规则：`AGENTS.md`
- 需求：`docs/PROJECT_REQUIREMENTS.md`
- 架构：`docs/ARCHITECTURE.md`
- 本阶段报告：`docs/PHASE_2_REPORT.md`

```
docker compose up -d
```

Windows 开发也可在仓库根目录分别启动 backend / execution-worker / frontend。交易设置存在 SQLite（`./data`），不在 `.env`。

未经确认不得连接 Hyperliquid 主网或发送真实订单。
