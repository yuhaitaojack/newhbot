# PHASE 11 REPORT — Control-Plane Authentication Guard

**日期：** 2026-09-04  
**状态：** COMPLETE / STOPPED  
**范围：** 非 Mock 控制面写请求的认证收口；未连接主网、未启动策略、未发送真实订单。

## 完成内容

- 新增 `CONTROL_API_TOKEN` 配置项。
- 非 Mock 模式下，所有 `/api` 的 POST/PUT/PATCH/DELETE 请求必须携带 `Authorization: Bearer <CONTROL_API_TOKEN>`；缺失、错误或未配置 token 时 fail-closed 返回 401。
- Mock 模式保持本地开发便利，不要求 token。
- 即使带有效 token，`/api/trading/signal` 仍保持 Mock-only，不能成为生产策略信号旁路。
- `.env.example` 与 API 设计文档已同步说明；token 仅作为环境密钥，不写入 SQLite。

## 验证

- 策略/控制器专项：**32 passed**。
- backend 完整回归：**84 passed**, 2 个既有 warning。
- 未修改测试断言来掩盖问题。

## 边界与后续

- 当前 Compose 仍为 `EXECUTION_MODE=mock` 与 `EXECUTION_ENABLED=false`，所以本地 UI 行为不受影响。
- 真实 Hyperliquid 前仍需单独完成只读复核、行情源选择、常驻策略进程/调度和主网授权；本 Phase 不改变这些限制。

## 安全结论

未读取 `.env` 实值，未提交密钥，未调用任何主网写接口。完成后按 `AGENTS.md` 停止，等待下一 Phase 指示。
