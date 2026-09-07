# PHASE 144 REPORT — 主网实盘 5 LONG + 5 SHORT 流程验证

**日期：** 2026-09-06  
**状态：** BLOCKED / 未完成目标；已安全停止。  
**目标：** 经现有 `StrategyRuntime → TradingController → Worker → Hummingbot → Hyperliquid` 路径完成 5 次 LONG 和 5 次 SHORT 的开仓、交易所确认、策略 CLOSE、reduce-only 平仓和 FLAT 确认。

## 结果

- 目标 **未完成**：完成的完整策略轮次为 `0/10`；SHORT 完成 `0/5`。
- 第一次正式 Controller 启动成功并进入 `RUNNING`，随后由 `ema5break` 产生 LONG 信号，Controller→Worker→Hyperliquid 的真实开仓请求成功，交易所确认 LONG `0.00013`。
- 测试夹具的 CLOSE 快照首次返回 `HOLD`，因此脚本按安全规则停止，没有继续开仓；随后通过正式 Controller 发出 reduce-only CLOSE，交易所确认 `FLAT/0`。
- 重新尝试 10 轮时，Controller 在启动同步阶段收到 Worker/交易所 `503 Service Unavailable`，进入 `RECOVERY`，未再发送开仓单。
- 主网最终只读复核：BTC-USD `FLAT/0`、全账户无挂单、无 foreign position、可用余额约 `15.05014`。

## 安全与路径核验

- 未调用 UI、脚本或直连交易所订单 API 绕过 Controller。
- 真实订单只在 Controller `handle_signal` → Worker `place_order` 路径发生；平仓使用 `reduce_only=true`。
- 未自动反手；开仓与平仓分开执行。
- 临时 live Compose 项目已停止并移除；默认 Compose 仍为 Mock / `EXECUTION_ENABLED=false`。
- 未打印或写入仓库真实密钥。

## 工程变更与验证

- 新增 Backend→Worker 写请求超时配置：默认 `60s`，可由 `EXECUTION_WORKER_WRITE_TIMEOUT_SECONDS` 覆盖；读请求仍由独立的 `EXECUTION_WORKER_READ_TIMEOUT_SECONDS` 控制。
- 新增本 Phase 的隔离执行夹具与残余仓位清理夹具；不改变默认启动行为。
- `python -m pytest backend/tests -q`：`159 passed`。
- 多次隔离容器运行均已清理；最终 live 只读复核确认空仓、无挂单。

## 停止原因

交易所上游在多次启动/同步期间出现 `429` 与 `503`，且本次账户可用资金约 15 美元、单笔最小名义价值为 10 美元，继续重试会增加启动不确定性和资金风险。按 Recovery 禁止开仓规则，本 Phase 在未完成 10 轮目标的情况下停止，等待用户明确要求后再安排下一 Phase。
