# PHASE 13 REPORT — Read-only Candle Data Bridge

**日期：** 2026-09-04  
**状态：** COMPLETE / STOPPED  
**范围：** 为后续策略循环提供只读 OHLCV 数据接口；未启动策略、未启用执行、未发送订单。

## 完成内容

- Worker 新增 `GET /rpc/candles?symbol=&interval=&limit=`。
- Hyperliquid 适配器使用官方 Info API `candleSnapshot` 获取公开 K 线，限制 interval 白名单和最多 5000 根；该请求不携带钱包签名，也不调用任何交易写接口。
- Mock 适配器返回空 K 线，避免本地 Mock Compose 误访问公网行情。
- Backend ExecutionClient 增加 candle DTO 接口，控制面新增 `GET /api/market/candles`。
- `/api/market/candles` 在 `EXECUTION_MODE=mock` 下明确返回 403，只有显式 Hyperliquid 模式才允许读取行情。
- API 设计文档补充两层行情接口。

## 验证

- Backend 完整回归：**86 passed**, 2 个既有 warning。
- Execution Worker 回归：**79 passed, 13 skipped**；skip 仍为本机缺少官方 Hummingbot 镜像/真实运行环境。
- 新增不支持 interval 的无网络测试，确认非法请求不会触发外部访问。

## 当前距离自动实盘循环的差距

- 尚未实现常驻 candle feed、去重已闭合 K 线、断线重连、节流和监督式策略循环。
- `/api/strategy/tick` 仍要求调用方提供快照，不会自动拉取 K 线或自动启动。
- 任何主网执行开关、主网写请求仍需用户在临近执行时单独明确确认。

## 安全结论

本 Phase 保持 `EXECUTION_ENABLED=false`，未读取或提交密钥，未调用主网交易写接口。完成后按 `AGENTS.md` 停止，等待下一 Phase 指示。
