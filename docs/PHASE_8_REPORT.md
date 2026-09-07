# PHASE 8 REPORT — Mock Strategy Runtime

**日期：** 2026-09-04  
**状态：** COMPLETE / STOPPED  
**范围：** 仅本地 mock；未连接 Hyperliquid 主网，未发送真实订单。

## 完成内容

- 新增 `POST /api/strategy/tick`：接收一份只读快照，加载当前已激活版本，并将策略输出限制为 `LONG` / `SHORT` / `CLOSE` / `HOLD`。
- 策略在独立 Python 子进程中执行，使用 `-I -S`、最小 builtins、无用户环境变量和 2 秒 wall-clock 超时；异常/超时返回 HOLD 语义的失败结果，不调用 Controller。
- tick 会重新查询执行层持仓，并覆盖请求快照中的 `symbol`、`position_side`、`entry_price`，避免用伪造快照绕过持仓安全检查。
- 有效信号唯一通过 `TradingController.handle_signal` 执行；策略运行时没有 connector、钱包、密钥或下单依赖。
- `PUT /api/settings` 不再接受通过 `active_strategy` / `active_strategy_version` 绕过 activate 流程的修改；策略切换仍只能走停止、扁平、无 unresolved 的 activate 门闩。

## 验证

- `backend`: **82 passed**, 2 个既有 warning（Starlette TestClient deprecation、pytest cache 权限/路径 warning）。
- 策略运行时与上传专项：**20 passed**。
- `python -m compileall -q app`: passed。
- `git diff --check`: passed；仅有既有 CRLF 转换提示，无 whitespace error。

## 明确未完成

- 尚未接入 K 线/行情采集器。
- 尚未实现常驻策略进程、supervisor、自动 tick 调度或自动启动。
- `/api/strategy/tick` 仍是本地 mock 开发接口，不是生产实盘接口；`execution_mode != mock` 时返回 403。
- 子进程限制符合项目 v1 个人单用户威胁模型，但不是强 OS/Docker 多租户隔离；Linux network namespace 等强化隔离应单独立 Phase。

## 安全结论

本 Phase 未修改 Compose 的默认禁用执行配置，未读取 `.env`，未武装 worker，未进行任何真实交易。完成后按 `AGENTS.md` 停止，等待下一 Phase 指示。
