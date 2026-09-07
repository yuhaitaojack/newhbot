# PHASE 23 REPORT — Read-only Candle Rate Limiting

**日期：** 2026-09-05  
**状态：** COMPLETE  
**范围：** 降低策略循环重复请求 Hyperliquid K 线导致限流的风险。

## 完成内容

- 在 `HyperliquidExecutionAdapter.get_candles()` 增加按 symbol、interval、limit 的短 TTL 内存缓存。
- 5 分钟 K 线最多每 30 秒访问一次上游；较短周期使用不低于 5 秒的相应 TTL。
- 只缓存公开只读 K 线；仓位、余额、挂单、订单和成交查询完全不缓存。
- 上游请求失败时不写入缓存，保持原有错误和 Recovery 安全路径。

## 验证证据

- Execution worker 本地测试：`80 passed, 13 skipped`。
- 新增测试确认相同 K 线查询在 TTL 内只产生一次上游请求。
- Backend 既有完整回归：`92 passed, 1 warning`。
- Frontend 构建成功，`git diff --check` 无错误。
- 当前线上旧 worker 仍保持运行，Backend 状态为 `RUNNING`、worker `READY/LIVE`、策略循环运行、`last_error=null`、信号 `HOLD`、仓位 `FLAT 0`、无订单。

## 部署与恢复验证

- Docker Hub 基础镜像当时不可拉取；随后使用本地正在运行的同版本派生 worker 镜像作为临时构建基础层，仅覆盖仓库最新代码，未修改 Dockerfile 或服务架构。
- execution-worker 已成功重建并重启；重启后 3 分钟日志无 `ERROR`、`Traceback`、`429`、`500` 或 `503`。
- 重启后 Backend 自动完成同步并恢复策略循环，状态为 `RUNNING / READY / LIVE`，`last_error=null`，信号 `HOLD`，仓位 `FLAT 0`，无订单。
- 浏览器 Dashboard 重启后加载成功，显示运行中、最新本地 K 线时间和零值格式化结果。

## 安全结论

- 未发起真实开仓、平仓、撤单或紧急停止。
- 未绕过 Trading Controller 或 Recovery。
- 未读取、打印或写入真实密钥。

本 Phase 报告完成后停止，等待用户下一步指示。
