# PHASE 20 REPORT — Dashboard Control Auth and Chinese UX

**日期：** 2026-09-05  
**状态：** COMPLETE  
**范围：** 修复 Dashboard 控制按钮 401，并完成交易界面中文化与悬停说明。

## 完成内容

- 前端 live compose 构建时注入本地 control token，所有非 GET API 请求自动携带 `Authorization: Bearer ...`。
- `启动交易` 按钮已实测返回 `成功 state=RUNNING`，不再出现 `401 control API authentication required`。
- Dashboard、交易设置、策略管理、订单记录、成交记录、系统事件完成交易术语汉化。
- 控制按钮、状态卡片、交易设置字段、策略上传/激活和记录页面标题均增加问号悬停说明，并保留可访问性文本。
- frontend 重新构建成功并重新部署；Dashboard 已打开并验证可见。

## 实时验证

- system：`RUNNING`
- `trading_enabled=true`
- strategy loop：`RUNNING`
- worker：`READY / LIVE`
- loop error：无
- latest signal：`HOLD`
- position：`FLAT`
- start button：成功返回 `state=RUNNING`

## 注意

控制 token 只通过 live compose 的构建/运行环境注入，未写入 Git；compose 默认仍为执行关闭。当前策略继续运行，账户仓位比例低于交易所最小名义金额时，Controller 会拒绝不合规开仓，不会绕过交易所规则。
