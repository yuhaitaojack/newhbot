# Phase 124 Report

## 目标

验证 `EXECUTION_ENABLED=true` 的认证 testnet armed 启动路径，在没有 Backend heartbeat 时不会错误开放交易。

## 验证

- 使用本机未跟踪凭据文件只读挂载，强制 `HYPERLIQUID_DOMAIN=hyperliquid_perpetual_testnet`。
- 认证连接成功，账户读取成功，user stream 存在。
- 余额、持仓、挂单、行情和 K 线只读查询均成功。
- 连接器内部状态为 `READY/LIVE`，但 Worker 健康门禁为 `ready=false`、`backend_heartbeat_ok=false`。
- 未调用 configure，未设置杠杆，未发送任何订单。

## 结论

armed testnet 连接具备正确的认证和安全门禁；Backend heartbeat 是进入真实执行的必要条件，符合“执行链必须由 Controller 驱动”的要求。

## 待授权动作

下一阶段需要进行 testnet 的最小外部写入验证：设置持久化杠杆、提交极小限价单、确认订单状态、受控撤单，并验证无持仓残留。该动作会改变 testnet 账户状态，需用户在当前会话明确确认后执行。主网仍禁止连接和下单。

