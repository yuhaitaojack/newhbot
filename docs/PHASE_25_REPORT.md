# Phase 25 Report

## 目标

确保已持久化的 `RECOVERY` 状态不会因为进程重启、Worker 暂时恢复或本地交易意图仍为 enabled 而自动回到 `RUNNING`。

## 最小变更

- `backend/app/recovery/manager.py`
  - 启动 bootstrap 在处理未解决订单和急停后，优先保留已持久化的 `RECOVERY`。
  - 仅后续明确的控制面启动流程可以再次尝试从 Recovery 恢复。
- `backend/tests/test_startup_and_loop_control.py`
  - 增加跨三次应用生命周期的回归测试：第一次正常运行，第二次因交易所查询失败进入 Recovery，第三次查询恢复后仍保持 Recovery 且循环停止。

## 验证结果

- 针对性测试：`6 passed`。
- 后端完整测试：`95 passed, 1 warning`。
- 后端镜像重建、容器重启成功。
- 前端重新启动以刷新 nginx 对后端容器的 upstream 地址。
- API 实际状态：
  - `system_state=RECOVERY`
  - `trading_enabled=true`（保留用户意图，不等于允许执行）
  - `worker_state=RECOVERING`
  - `sync_status=CONFLICT`
  - `strategy_loop_running=false`
  - 交易所镜像持仓 `FLAT 0`
- 浏览器实际验证：Dashboard 显示 `RECOVERY`、Worker `RECOVERING`、策略循环“已停止”，且五个交易控制按钮可见。
- 未点击任何真实交易动作，未发送订单。

## 安全结论

Recovery 现在具有跨重启的持久化安全边界；账户状态查询不可用时不会因自动启动流程而恢复开仓能力。当前系统继续保持安全阻断。

## 停止点

Phase 25 已完成。未经用户明确要求，不开始下一 Phase。
