# NEWHBOT 项目交接报告

**交接时间：** 2026-09-05（Asia/Taipei）  
**工作区：** `E:\\yu_cursor_workspace\\newhbot`  
**项目：** Hummingbot + Hyperliquid 单策略永续交易系统  
**交接目的：** 供新会话继续修复 Dashboard、策略循环和实盘运行问题

> 本文是当前会话的工作交接资料，不是新的开发规范。仓库根目录 `AGENTS.md` 是最高优先级的开发与交易安全规则。

> **时效说明（2026-09-06）：** 本文是 2026-09-05 的历史交接快照，已被后续 Phase 报告取代。当前实现与验证结论以最新的 `docs/PHASE_132_REPORT.md` 为准。默认 `docker compose` 使用 Mock 执行、关闭真实执行；最近已验证状态为 `STOPPED`、`FLAT/0`、Worker `READY/LIVE`。本文中的“当前”“未完成”“主网运行”等表述均应按历史快照理解，不得据此连接主网或发单。

## 1. 当前结论

历史快照曾记录项目推进到 `ema5break v1` 策略循环接入 Controller，并曾使用 Hyperliquid 主网执行 worker。该描述不是当前运行状态；当前默认环境为 Mock 且真实执行关闭。

当时会话最后发现了若干需要收尾的问题；这些问题已在后续 Phase 逐项修复，以下内容保留作为历史线索：

1. 点击 Dashboard 的“启动交易”后，策略循环曾显示：`HTTPStatusError: Server error '500 Internal Server Error'`，来源是 worker 的 `/rpc/candles?symbol=BTC-USD&interval=5m&limit=200`。
2. worker 日志显示 Hummingbot/Hyperliquid websocket 曾短暂断开，worker 进入 `RECOVERING`，同步状态显示 `CONFLICT`。之后 candle 请求又能返回 200，说明至少包含瞬时恢复过程。
3. 策略循环代码会把一次异常写入 `last_error`，成功 tick 后没有清空，因此界面可能一直显示已经恢复的旧错误。
4. Dashboard 的“最新 K 线”直接显示毫秒时间戳，例如 `1788610500000`，需要转换为本地日期时间。
5. UI 中此前新增的 `HelpTip` 问号提示需要全部移除。

历史新会话目标已完成。后续工作仍必须遵守“不绕过 Recovery、不手动下单”的约束，并以最新 Phase 报告为准。

## 2. 历史运行状态（非当前状态）

2026-09-05 最后一次浏览器/API观察到的状态如下，仅供追溯，不能作为当前状态：

```text
system_state: RUNNING
trading_enabled: true
strategy_loop_running: true
active_strategy: ema5break
active_strategy_version: v1
last_signal: HOLD
position: FLAT
worker_state: RECOVERING（当时正在恢复，需重新确认）
worker_ready: false（当时正在恢复，需重新确认）
sync_status: CONFLICT（当时正在恢复，需重新确认）
last_candle_timestamp: 1788610500000（原始毫秒值）
```

worker 后续日志里曾出现 candle HTTP 200，且 candle 数据价格约为 79617；但必须重新查询 `/health`、`/api/status` 和 `/api/strategy/loop`，不能把旧快照当作当前状态。

账户资金此前观察约为 `15.054942`，仓位比例为 10%。Hyperliquid 最低名义金额约束可能使开仓被拒；除非用户明确改变风险/仓位设置，不要自行提高仓位比例或修改最小下单金额规则。

## 3. 安全边界（必须遵守）

完整规则见 `AGENTS.md`，关键点如下：

- 策略只能输出 `LONG` / `SHORT` / `CLOSE` / `HOLD`，策略不能访问交易所、connector、密钥或下单函数。
- 所有开仓、平仓、撤单、紧急停止必须经过 `TradingController`。
- 任何时刻最多一个 Hyperliquid 永续持仓；有仓时拒绝新的 `LONG` / `SHORT`。
- 禁止自动反手；反手必须先独立完成 `CLOSE`，之后无仓时再由后续信号开仓。
- Hyperliquid 真实状态优先于 SQLite；冲突进入安全处理。
- `RECOVERY`、对账失败、交易所查询失败期间禁止开仓。
- 不得为了验证 UI 而点击真实开仓、平仓或发送测试订单。
- 不要输出、提交或写入任何私钥、API secret、助记词或 `.env` 实值。
- 只使用环境变量/本地未跟踪配置；报告中只写“已设置/未设置”，不要写值。
- 本项目当前确实有用户在此前会话中明确授权主网运行，但这不等于允许旁路 Controller 或人工发单。

## 4. 已完成的主要工作

### 后端与交易控制

- Trading Controller、Position Guard、Recovery、审计和状态镜像已接入。
- 真实执行路径为：  
  `Dashboard/API → TradingController → HttpExecutionClient → execution-worker → Hummingbot/Hyperliquid`
- Worker 不向宿主机发布 8001；Backend 通过 Docker 内部网络访问。
- Controller 已包含最多一仓、有仓禁止开仓、禁止自动反手、Recovery 禁止开仓、订单状态未知不重发等保护。
- `ema5break` 策略已注册并激活为 `ema5break v1`。
- 策略运行循环文件为 `backend/app/strategy/loop.py`，当前会读取 K 线、读取仓位、加载策略运行时、得到信号并交给 Controller。
- Dashboard/API 已暴露策略循环运行状态、最近错误、最近 K 线时间戳等字段。

### Worker 与主网

- `execution-worker` 已有 Hyperliquid 适配、连接、只读查询、对账和执行保护。
- 当前运行使用 live override 文件：`docker-compose.live-readonly.example.yml`。
- live override 不应提交密钥；主网环境变量由 PowerShell 会话临时注入。
- 真实账户密钥来源是用户本地文件：`C:\\Users\\Admin\\Desktop\\hyper.txt`。不要读取后在输出或文档中打印内容。

### 前端

- Dashboard、Settings、Strategy、Orders、Trades、Events 已汉化大部分交易术语。
- Docker Compose 的 Frontend Nginx 会在运行时向代理请求注入控制面 Bearer token；token 不再编译进浏览器 JavaScript，也不再使用 `VITE_CONTROL_API_TOKEN` build arg。
- 本会话期间添加过 `frontend/src/components/ui/help-tip.tsx` 及多个 `<HelpTip>`；该项已在后续 Phase 完成，文件已删除且当前源码无 `<HelpTip>` 引用。

## 5. 历史未完成修改（已由后续 Phase 处理）

本节记录的是交接时的待办，不是当前待办。策略循环错误清理、Recovery 安全检查、时间戳显示和 HelpTip 清理均已在后续 Phase 完成；如需继续开发，应先查阅最新 Phase 报告和当前源码，避免重复修改。

### A. 策略循环恢复与错误显示

文件：`backend/app/strategy/loop.py`

建议最小安全修复：

1. `_run()` 中 `await self._tick()` 成功返回后清空 `self.last_error`，使旧错误不会永久显示。
2. 每次 tick 在读取 candle/仓位前检查 execution worker 是否 READY。
3. 如果 worker 暂时不 READY，可调用现有的 `HttpExecutionClient.connect()` 进行安全连接/恢复尝试；连接失败继续保持错误状态，绝不能绕过 worker 的 Recovery 检查开仓。
4. worker 仍非 READY 时，只记录错误并跳过本 tick；不要调用开仓 Controller 信号路径。
5. 重新确认 Controller/Recovery 的现有状态模型，避免仅把 UI 显示改成 RUNNING 而掩盖 `RECOVERING`。

推荐先检查：

- `backend/app/execution/protocol.py`
- `backend/app/execution/client.py`
- `execution-worker/app/runtime.py`
- `execution-worker/app/hyperliquid_adapter.py`
- `backend/app/controllers/trading_controller.py`

不要仅靠吞掉 HTTP 500 来“修复”；必须保证恢复期间没有真实开仓。

### B. Dashboard 最新 K 线格式

文件：`frontend/src/pages/DashboardPage.tsx`

将 `status.strategy_loop_last_candle_timestamp` 从毫秒值转换为人类可读的本地时间，例如：

```text
最新 K 线：2026/09/05 20:15:00
```

同时建议把 `0E-12` 等 Decimal 零值在持仓和盈亏卡片显示为 `0`，避免用户误以为数值异常。不要改变后端交易数值或精度，只改变显示格式。

### C. 移除问号提示（已由后续 Phase 完成）

历史建议是删除 `frontend/src/components/ui/help-tip.tsx`，并移除以下文件的 import 和 JSX；该文件当前已不存在，前端源码中也已无 `<HelpTip>` 引用：

- `frontend/src/pages/DashboardPage.tsx`
- `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/pages/Lists.tsx`

如果用户要求所有悬停提示都消失，也移除 `frontend/src/App.tsx` 导航项的 `title` 属性；普通中文按钮文本保留。

## 6. 关键文件索引

```text
AGENTS.md                                      最高优先级交易安全规则
docker-compose.yml                             默认 Compose
docker-compose.live-readonly.example.yml       当前 live override 示例
backend/app/strategy/loop.py                   策略循环
backend/app/strategy/runtime.py                策略安全运行时
backend/app/controllers/trading_controller.py  唯一交易控制入口
backend/app/controllers/position_guard.py      仓位/风控守卫
backend/app/execution/client.py                Backend → Worker HTTP 客户端
execution-worker/app/runtime.py                Worker 状态、Recovery、RPC
execution-worker/app/hyperliquid_adapter.py    Hyperliquid 适配
frontend/src/api.ts                             前端 API 与认证 token
frontend/src/pages/DashboardPage.tsx           Dashboard
frontend/src/pages/SettingsPage.tsx             交易设置
frontend/src/pages/Lists.tsx                   策略/订单等列表页
strategies/ema5break/                          ema5break 策略源码
data/newhbot.db                                 本地 SQLite，已被 gitignore
docs/PHASE_19_REPORT.md                         策略运行阶段报告
docs/PHASE_20_REPORT.md                         最近阶段报告
```

## 7. 历史启动、检查与重建说明（不要直接照此连接主网）

本节保留历史操作线索。当前默认开发流程使用 Mock 且真实执行关闭；任何主网操作都必须重新核对 `AGENTS.md` 并取得当前会话的明确确认。

### 7.1 先做只读检查

不要先点击启动或发单，先获取当前状态：

```powershell
docker compose ps
docker compose logs --tail=120 execution-worker
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/status
Invoke-RestMethod http://127.0.0.1:8000/api/strategy/loop
```

Dashboard 地址：`http://127.0.0.1:8080/`

### 7.2 live 环境变量注入

历史上曾需要从本地未跟踪配置读取密钥并在 PowerShell 当前进程中设置；本交接文档不再作为主网操作指令，禁止直接照此执行：

- `HYPERLIQUID_PERPETUAL_ADDRESS`
- `HYPERLIQUID_PERPETUAL_SECRET_KEY`
- `CONTROL_API_TOKEN`
- `EXECUTION_MODE=hyperliquid`
- `EXECUTION_ENABLED=true`
- `HUMMINGBOT_LIVE_CONNECTOR=true`

控制 token 每次临时生成即可。严禁把任何值写入文档、源码或 Git。

### 7.3 重建顺序

若修改了 backend loop：重建 backend；若修改了前端：重建 frontend。随后重新创建 backend/frontend 容器，保持 worker 运行；使用当前控制 token 调用：

1. `POST /api/trading/stop`
2. 确认 worker READY、仓位 FLAT/或正确镜像状态
3. `POST /api/trading/start`
4. `POST /api/strategy/loop/start`

这些调用必须带 `Authorization: Bearer <当前 CONTROL_API_TOKEN>`，但不要在交接文档或最终回复显示 token。

## 8. 历史验证标准

以下标准是交接时的验收清单，后续 Phase 已覆盖其中相关项目；不能替代当前测试结果。

代码完成后至少验证：

- Backend 测试通过：`pytest -q`。
- Worker 相关测试通过：`pytest -q`。
- Frontend 构建通过：`npm run build`。
- `git diff --check` 无错误。
- `/api/status` 中 worker 状态与 sync 状态真实一致。
- `/api/strategy/loop` 中 `running=true`，恢复后 `last_error` 为空或为当前真实错误。
- Dashboard 不再显示问号。
- Dashboard 最新 K 线显示日期时间，不显示 13 位毫秒整数。
- 最近信号仍为 `HOLD` 或经过 Controller 的合法信号。
- 未出现未经用户策略信号和 Controller 批准的订单。
- 若 worker 处于 `RECOVERING`/`CONFLICT`，界面应如实显示并禁止开仓。

## 9. Git 与工作区注意事项

当前工作区有大量未提交和未跟踪文件，属于本项目现有工作成果。不要执行：

- `git reset --hard`
- `git checkout -- ...`
- 清空工作区或删除未跟踪文件
- 将 live 密钥写入 `.env.example`、Compose、日志或报告

本交接文档本身未包含密钥。新会话完成本轮修复后，按 `AGENTS.md` 要求新增对应的 Phase 报告，并在该 Phase 完成后停止等待用户指示。

## 10. 给新会话的首条工作指令

> 读取 `AGENTS.md` 和本文件。先只读检查 Docker、`/api/status`、`/api/strategy/loop` 与 worker 日志；确认当前是否仍在实盘运行。然后修复 `StrategyLoop` 的 worker 恢复/旧错误清理逻辑，格式化 Dashboard 最新 K 线时间，删除所有 HelpTip 问号。不要手动下单，不要绕过 TradingController，不要在 Recovery 状态开仓。构建、测试、重启并用内置浏览器验证，最后写入新的 Phase 报告。
