# PHASE 145 REPORT — ema5break 五分钟整点监控

**日期：** 2026-09-06  
**状态：** STOPPED_RECOVERY；监控已停止，目标未完成。

## 当前状态

- 监控进程已停止，不会继续在后台检查或下单。
- 最后记录的交易所状态：BTC-USD `FLAT`，无已记录挂单。
- 完成计数：LONG `1/5`，SHORT `0/5`。
- 监控调度：只在每个 5 分钟边界后检查一次真实收盘 K 线；中间仅保留 Worker 安全心跳。

## 已完成交易

- 1 次 LONG：由真实 `ema5break` 信号触发，经 Trading Controller 开仓；随后策略发出 CLOSE，经 reduce-only 平仓并确认回到 FLAT。
- 未发生 SHORT 完整轮次。

## 新发现问题

在 18:20 整点检查时，真实 `ema5break` 再次产生 LONG 信号。账户当时已确认 FLAT，但 Controller 在持久化新的开仓意图时触发：

```text
sqlite3.IntegrityError: UNIQUE constraint failed: orders.symbol
```

该错误发生在写入 `PENDING_SUBMISSION` 订单记录阶段，交易所未收到这次新的开仓请求。监控器捕获异常后进入 `STOPPED_RECOVERY`，没有重试或绕过 Controller。

## 影响与处理

- 目标 5 LONG + 5 SHORT 未完成。
- 没有因为该异常产生重复订单或自动反手。
- 监控已停止；需要修复订单表的唯一约束/模型设计及对应迁移后，才能安全恢复监控。
- 默认 Mock 栈未纳入本次实盘监控。

## 建议的后续修复方向

1. 检查 `orders.symbol` 的唯一约束是否错误；同一交易对必须允许历史订单记录。
2. 增加迁移与回归测试，覆盖同一 symbol 的连续开仓-平仓轮次。
3. 在重新启用主网监控前，先用 Mock/测试数据库验证至少 10 个连续 round-trip 的持久化路径。
