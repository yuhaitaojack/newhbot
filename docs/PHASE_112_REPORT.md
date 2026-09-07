# Phase 112 Report

## 目标

验证 Docker 服务重启后的安全恢复与就绪状态，修复本地 Mock Worker 重启后永久 `NOT_READY` 的问题，并完成回归验证。

## 问题与最小修复

重启 Backend 和 Worker 后，Backend 状态仍正确保持 `STOPPED`、交易开关关闭、`FLAT/0`，但 Mock 适配器进程内的 `connected` 默认为 `False`，没有启动初始化，因此 Worker 永远报告 `NOT_READY/NONE`。

仅在 `execution_mode=mock` 时为 Worker 增加 FastAPI lifespan：进程启动时连接 Mock，进程关闭时断开 Mock。Hyperliquid 路径不自动连接，现有真实执行安全边界不变。

## 验证结果

- 修复前重启后：`worker_ready=false`、`worker_state=NOT_READY`、`sync_status=NONE`，预检正确禁止运行。
- 修复后重建并重启：约 3 秒内恢复 `worker_ready=true`、`worker_state=READY`、`sync_status=LIVE`。
- 重启前后持久化状态保持：`STOPPED`、交易开关关闭、`estop=false`、`FLAT/0`。
- Backend：`156 passed`，1 条既有 Starlette/httpx 弃用警告。
- Execution Worker：`96 passed, 1 skipped`。
- 浏览器重新加载 Dashboard：正确显示 `STOPPED`、`FLAT 0 BTC-USD`、Worker `READY`、同步 `LIVE`。

## 最终状态

正式栈为 Mock 模式，真实执行关闭；策略循环停止、未连接 Hyperliquid 主网、未读取真实密钥、未发送真实订单。

## 安全边界

本阶段只修改 Worker 的 Mock 启动生命周期和对应测试，没有修改 Trading Controller、策略信号、Hyperliquid 执行路径或数据库结构。
