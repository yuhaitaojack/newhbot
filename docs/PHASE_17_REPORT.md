# PHASE 17 REPORT — Live Preflight Funds Gate

**日期：** 2026-09-05  
**状态：** PARTIAL / NO-GO  
**范围：** 强化实盘前余额闸门；未发送订单、撤单或杠杆请求。

## 完成内容

- `/api/preflight` 现在同时记录并校验 `equity` 与 `available`。
- 只要任一值不为正，preflight 就拒绝 `ready_for_live`。
- 增加后端回归测试，覆盖 available balance 为零时的拒绝路径。

## 验证结果

- Backend：88 passed。
- Worker Hyperliquid adapter / read-only bridge：26 passed。
- 上一阶段 authenticated worker 探测：认证成功、Worker READY、FLAT、0 挂单，但 `equity_readable=false`。
- 本阶段独立公共账户查询：Hyperliquid Info API 返回 HTTP 502，无法确认当前可用保证金。

## 当前 NO-GO

- 账户权益/可用保证金尚未确认是正数。
- Docker Hub 基础镜像仍无法拉取，当前运行验证使用旧 worker 镜像；不能视为生产镜像已重建。
- 未确定首单策略版本、风险参数、仓位大小和杠杆；不得由 Agent 猜测。
- `EXECUTION_ENABLED` 继续保持 false，没有真实交易写操作。

## 安全结论

系统现在会在资金不可读或非正时阻止进入实盘就绪状态。下一阶段必须先在网络恢复后重建 worker，并完成 authenticated read-only preflight；只有资金、仓位、挂单、策略和参数全部通过，才可进入用户明确指定的首单执行阶段。
