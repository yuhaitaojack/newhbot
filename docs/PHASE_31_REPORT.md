# Phase 31 Report

## 目标

限制运行中的交易设置变更，避免仓位比例、杠杆、交易对等配置在交易进行期间发生漂移。

## 最小变更

- `backend/app/api/routes.py`
  - `PUT /api/settings` 仅在系统为 `STOPPED` 且交易开关关闭时允许保存。
  - 运行中保存返回 HTTP 409，数据库值保持不变。
- `backend/tests/test_api_controller.py`
  - 增加运行中修改设置的拒绝及参数不变回归测试。

## 验证结果

- 针对性测试：`14 passed`。
- Backend 完整测试：`96 passed, 1 warning`。
- 部署后浏览器测试：
  - STOPPED 状态点击“保存设置”显示“已保存”。
  - RUNNING 状态点击“保存设置”显示 `409: settings can only be changed while trading is STOPPED`。
  - 最后点击“停止交易”，恢复安全停止状态。
- 最终状态：`STOPPED`、Worker `READY/LIVE`（本地 Mock）、循环停止、持仓 `FLAT 0`、无未完成订单。
- `git diff --check` 无 whitespace error，仅有已有 CRLF 转换提示。
- 未连接 Hyperliquid，未发送真实订单。

## 停止点

Phase 31 已完成。未经用户明确要求，不开始下一 Phase。
