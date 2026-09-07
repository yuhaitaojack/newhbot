# PHASE 14 REPORT — Explicit Supervised Strategy Loop

**日期：** 2026-09-04  
**状态：** COMPLETE / STOPPED  
**范围：** 常驻策略循环骨架与显式启停；未启用执行、未发送真实订单。

## 完成内容

- 新增 `StrategyLoop`，以独立 asyncio task 运行，应用退出时回收。
- 新增 `GET /api/strategy/loop`、`POST /api/strategy/loop/start`、`POST /api/strategy/loop/stop`。
- 循环只有在显式 start 后运行；每轮检查持久化 `RUNNING`/`trading_enabled`，否则安全等待。
- 每轮读取 Worker 只读 K 线，按最新 candle timestamp 去重；查询交易所持仓，组装策略快照，调用受限 `StrategyRuntime`，再统一进入 `TradingController`。
- 循环 tick 记录 `strategy_loop_tick` 审计；策略异常由监督循环捕获并记录，不会自动重启交易状态或绕过 Controller。
- Mock Fake 支持可控 candle fixture，验证了显式启动、重复 candle 去重路径和停止。

## 验证

- 策略运行时/上传/循环专项：**25 passed**。
- Backend 完整回归：**87 passed**, 2 个既有 warning。
- 未修改测试断言来掩盖问题。

## 当前距离实盘的差距

- 当前 Compose 仍为 `EXECUTION_MODE=mock`、`EXECUTION_ENABLED=false`。
- 需要在最新 Worker 镜像上做只读 live preflight，并确认 Hummingbot 真实运行环境支持 candle 读取与目标 pair。
- 需要补充 live 模式下的人工确认流程、最小名义/仓位数量验证和首单前审计证据；本 Phase 未触发。
- UI 尚未提供策略循环启停按钮，目前通过受保护 API 显式控制。

## 安全结论

本 Phase 没有自动启动循环，没有读取 `.env` 实值，没有连接主网写路径。完成后按 `AGENTS.md` 停止，等待下一 Phase 指示。
