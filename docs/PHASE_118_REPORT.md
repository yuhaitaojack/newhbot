# Phase 118 Report

## 目标

验证 Worker 故障期间 Dashboard 启动动作的 Recovery 门禁，并修复失败启动将 `trading_enabled` 持久化为 `true` 的状态不一致问题。

## 问题与最小修复

Worker 不可达时，`TradingController.start()` 原先在健康检查和交易所预检完成前就写入 `trading_enabled=True`；启动失败进入 Recovery 后，该开关可能残留为 `true`。

将赋值移动到全部 Worker 健康、连接、持仓、挂单和未决订单检查成功之后、进入 `RUNNING` 之前。失败启动现在保持交易开关关闭；没有改变 Controller、Recovery 或执行路径结构。

## 验证结果

- 停止 Mock Worker 后，Dashboard 显示 `RECOVERY` / `NOT_READY`。
- 点击“启动交易”返回 `execution worker unreachable; recovery required`，按钮暂时锁定，未产生订单。
- Worker 恢复后系统仍为 `RECOVERY`，但 `trading_enabled=false`，没有自动启动。
- 人工再次点击“启动交易”后成功进入 `RUNNING`；随后点击“停止交易”恢复 `STOPPED`。
- Backend 全量回归：`156 passed`，1 条既有 Starlette/httpx 弃用警告。

## 最终状态

- Health：`ok`；执行模式 Mock；Worker `READY/LIVE`。
- 系统：`STOPPED`、交易开关关闭、`estop=false`、策略循环停止。
- 持仓：`FLAT/0`；无真实主网连接、无真实订单。

## 安全边界

故障注入和恢复均在本地 Mock Worker 完成；未连接 Hyperliquid 主网，未读取真实密钥，未发送真实订单。
