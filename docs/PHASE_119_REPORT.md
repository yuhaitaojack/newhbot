# Phase 119 Report

## 目标

缩短 Backend 查询 Worker 故障时的等待时间，使控制面快速进入 Recovery，同时保留下单、撤单等执行请求的原有超时语义。

## 问题与最小修复

`HttpExecutionClient` 原来所有 RPC 共用默认超时。Worker 不可达时，Dashboard 的状态查询可能长时间等待。仅新增查询超时 `read_timeout=2s`，并将 health、worker status、持仓、余额、挂单、成交、行情、K 线等只读请求切换到该超时；连接、配置、心跳、杠杆、下单和撤单仍使用原有请求超时。

## 验证结果

- 目标查询故障注入后，`/api/status` 在约 6 秒内返回 `RECOVERY`，不再长时间阻塞。
- 故障期间 Dashboard 启动动作仍提示 `execution worker unreachable; recovery required`，未产生开仓调用。
- Worker 恢复后状态为 `READY/LIVE`，系统保持 `RECOVERY`、`trading_enabled=false`，没有自动启动。
- 最终通过 Controller 停止动作恢复 `STOPPED`。
- Backend 全量回归：`156 passed`，1 条既有 Starlette/httpx 弃用警告。

## 最终状态

- 执行模式 Mock，真实执行关闭。
- 系统 `STOPPED`、交易开关关闭、`estop=false`、持仓 `FLAT/0`、策略循环停止。
- 未连接 Hyperliquid 主网、未读取真实密钥、未发送真实订单。

## 安全边界

本阶段只调整内部 HTTP 查询超时和回归测试流程，没有改变 Trading Controller、Recovery 规则或真实执行路径。
