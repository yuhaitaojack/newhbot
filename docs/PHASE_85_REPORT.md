# Phase 85 Report

## 目标

修复 Backend 健康接口在 Worker HTTP 可达但 Worker 尚未就绪时仍报告总体 `ok` 的可观测性缺口。

## 修复

- `/api/health` 现在只有在 Worker 可达且 `ready=true` 时返回 `status=ok`。
- Worker 可达但 `ready=false` 时返回 `status=degraded`，同时保留具体 `worker_state` 和同步状态。
- 更新测试 Fake，使 `ready_flag` 同步反映到 `worker_status`，避免测试双重标准。
- 新增 Worker 未就绪时总体健康状态为 `degraded` 的回归测试。

## 验证

- 定向健康测试通过。
- Backend 全量：`149 passed`，1 个既有弃用警告。
- Backend 镜像已重建并部署。
- 部署后正式栈：`/api/health` 为 `ok + READY/LIVE`；系统 `STOPPED`、仓位 `FLAT/0`、策略循环停止。
- 日志无 `ERROR` 或 `Traceback`；`git diff --check` 无 whitespace error。
- 未连接 Hyperliquid 主网、未读取真实密钥、未发送真实订单。

## 结论

健康接口现在不会把未就绪 Worker 误报为可用。按仓库规则停止，等待下一 Phase 指示。
