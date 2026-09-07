# Phase 93 Report

## 目标

修复 Dashboard WebSocket 断线后不再重连的问题，保留 REST 轮询作为降级路径。

## 实施

- Dashboard 在 WebSocket `close` 后自动重连。
- 重连采用 1 秒起步、最大 10 秒的指数退避，避免后端故障时高频连接。
- 页面卸载时取消重连定时器并关闭 socket，避免泄漏或卸载后更新状态。
- 未改变 REST 命令、TradingController、Execution Worker 或认证边界。

## 验证

- `npm run build` 通过，TypeScript 检查通过。
- Frontend 镜像重建并重新创建容器成功。
- 浏览器 Dashboard 加载成功，五个控制按钮及 STOPPED/FLAT/Worker READY/LIVE 状态正常显示。
- 重启 Backend 模拟 WebSocket 断线；等待重连窗口后 Dashboard 仍可用，Backend health 恢复为 `ok`。
- 正式本地栈：Mock、`execution_enabled=false`、系统 STOPPED、交易开关关闭、持仓 FLAT/0。

## 安全边界

未连接 Hyperliquid 主网，未读取真实密钥，未发送任何订单。

