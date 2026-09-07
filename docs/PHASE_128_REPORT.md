# Phase 128 Report

## 目标

统一 Worker Runtime 的杠杆写入安全门禁，防止执行模式下在未 READY、Recovery、网络降级或 Backend heartbeat 失效时直接修改账户杠杆。

## 实现

- `WorkerRuntime.set_leverage` 在执行模式下要求 Worker 为 `READY` 且 Backend heartbeat 有效。
- 未满足条件时在到达 connector 前抛出 `ExecutionDisabled`。
- Mock 与执行关闭路径保持原有行为；紧急撤单/平仓接口不受该门禁影响。

## 验证

- 杠杆/heartbeat 针对性测试：`32 passed`。
- Worker 全量测试：`106 passed, 1 skipped`。
- Worker Docker 镜像重建成功。
- 最终运行态：`STOPPED`、交易开关关闭、紧急停止关闭、Worker `READY/LIVE`、持仓 `FLAT/0`。
- 未执行任何 testnet 或主网写操作。

## 待授权动作

testnet 最小真实写入演练仍需用户当前会话明确确认；主网仍禁止连接和下单。

