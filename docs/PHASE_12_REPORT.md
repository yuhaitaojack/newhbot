# PHASE 12 REPORT — Read-only Live Preflight

**日期：** 2026-09-04  
**状态：** COMPLETE / STOPPED  
**范围：** 实盘前只读准入检查；未连接主网写路径、未启动策略、未发送订单。

## 完成内容

- 新增 `GET /api/preflight`，统一检查：执行模式、Worker readiness、执行开关、控制面 Token、系统状态、estop、指定交易对持仓、全部持仓数量/外部持仓、挂单、SQLite 未决订单、余额、已激活策略及策略文件。
- 返回 `ready_for_live`、结构化检查字段和明确 `reasons`；任何检查失败均为 NO-GO。
- preflight 全程只读，不调用 place/cancel/set_leverage，不修改 SQLite 状态。
- API 设计文档已补充该接口。

## 验证

- 策略/控制面专项：**20 passed**。
- backend 完整回归：**85 passed**, 2 个既有 warning。
- Mock 环境 preflight 正确返回 NO-GO，且 Fake Execution 的 place/cancel/set_leverage 调用计数保持不变。

## 当前距离实盘的明确差距

- 当前 Compose 仍为 `EXECUTION_MODE=mock`、`EXECUTION_ENABLED=false`。
- 尚未完成真实 K 线行情源和常驻策略循环。
- 尚未进行带用户授权的 Hyperliquid 只读账户复核。
- 历史主网 oneshot 曾发生小名义 CLOSE 拒单；真实执行前仍需在最新 worker 镜像上复核并修复/验证该路径。

## 安全结论

本 Phase 未读取 `.env` 实值，未启用执行开关，未连接主网写接口。完成后按 `AGENTS.md` 停止，等待下一 Phase 指示。
