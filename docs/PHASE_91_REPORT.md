# Phase 91 Report

## 目标

补齐策略参数“启用/禁用 + 当前值编辑”的 Web UI 闭环，并确认参数持久化与运行时 effective value 规则不被破坏。

## 实施

- 新增 `PUT /api/strategy/parameters/{parameter_id}`。
- 仅允许当前激活策略版本的参数修改，且仅允许系统处于 `STOPPED` 且未开启交易时修改。
- 对 `int`、`float/number/decimal`、`bool`、`string` 做类型校验，并校验 manifest 提供的最小/最大值。
- 更新参数时写入 SQLite 并记录审计事件；`enabled=false` 继续使用策略默认值，`enabled=true` 使用持久化的 `current_value`。
- 策略管理页新增参数卡片，可点击启用自定义值、编辑并保存当前值，同时展示生效值、默认值和范围。

## 验证

- Backend：`152 passed`，1 个既有 Starlette/httpx 弃用警告。
- Frontend：`npm run build` 通过。
- 浏览器点击验证：策略管理页显示 6 个参数；点击 `ema_period` 的“启用自定义值”后显示保存成功，API 返回 `enabled=true`；点击保存值无错误。
- 持久化验证：恢复 `ema_period` 为 `enabled=false/current_value=5` 后重启 Backend，读取结果保持一致。
- 正式本地栈：health `ok`，execution mode `mock`，`execution_enabled=false`，Worker `READY/LIVE`；系统 `STOPPED`、交易开关关闭、持仓 `FLAT/0`。
- `git diff --check` 无实际空白错误；仅有工作区既存 CRLF 转换警告。

## 安全边界

本 Phase 未连接 Hyperliquid 主网、未读取或写入真实密钥、未发送真实订单，未改变交易执行架构。

