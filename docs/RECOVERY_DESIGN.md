# 故障恢复设计

系统状态机总图见 `docs/TRADING_STATE_MACHINE.md`。本节按故障场景规定行为。全程禁止 Recovery 开仓。

## 1. 恢复原则

1. Hyperliquid 是仓位真相。
2. SQLite 是意图与审计。冲突时改本地，不「修正」交易所。
3. 任何 UNKNOWN 订单未关闭前，系统不得 RUNNING 开仓。
4. 重启后即使对账完美，也不得因为「策略现在是 LONG」而补开仓；必须等待 **新的** 信号周期且 Guard 通过。
5. 自动恢复 RUNNING 的条件见状态机文档；不满足则停在 RECOVERY 或 STOPPED。

## 2. 场景

### A. 程序正常重启

STARTING → CONNECTING → SYNCING → RECONCILING。

- 若 `running=true` 且无 UNKNOWN 且仓位一致 → RUNNING（继续持有，策略从 HOLD 开始）。
- 若 `estop=true` → 保持停止，需人工解除。

### B. Docker 重启

与 A 相同。Compose `restart: unless-stopped`。SQLite 与密钥必须在 volume 上，不能只在容器可写层。

### C. Windows 主机重启

Docker Desktop / WSL2 起来后 Compose 拉起。若 Docker 未装（PHASE 0 现状），谈不上自动恢复——这是部署前置，不是交易逻辑。

### D. Hummingbot / Execution Worker 崩溃

Backend 进入 CONNECTING。持仓仍在交易所。禁止开仓。Worker 起来后 SYNCING。若崩溃发生在 `place` 之后：按 UNKNOWN 流程查 `orderStatus(cloid)`。

### E. Backend 崩溃

Worker 应 **停止接受新的 place**（心跳丢失则 Worker 进入只读或退出）。已发出的交易所订单继续存在。Backend 恢复走 A。

Worker 对 Backend 做心跳租约；默认 30 秒无心跳时进入 DEGRADED 并拒绝新的非 reduce-only 开仓，**不自动平仓**（避免 Backend/UI 闪断导致误平）。已提交的减仓/平仓路径仍可执行；Backend 恢复后心跳自动恢复 READY。

### F. Web UI 崩溃

不影响交易。UI 重连拉 REST snapshot + WS。

### G. 本地网络断开

CONNECTING。禁止开仓。已提交未明订单 → UNKNOWN。恢复后先查单再决定。

### H. Hyperliquid 连接断开

官方：服务端会周期性断开，客户端必须重连；漏数据在 snapshot 或 info 补。行为同 G。

### I. 订单提交后进程崩溃

最危险。依赖步骤 4「先 COMMIT UNKNOWN 再发送」。恢复时用 cloid 查询。没有落库的崩溃 = 可能已下单但本地无记录：

- 用 `openOrders` + `clearinghouseState` 发现「无主」仓/单 → RECOVERY 人工。
- 因此 place 前 COMMIT 是硬要求。

### J. 成交后进程崩溃

交易所已有仓。本地可能仍 FLAT。RECONCILING 以交易所为准改成本地 LONG/SHORT。不补单。

### K. 平仓过程中崩溃

可能部分成交。恢复后若仍有仓：保持仓位，**不要自动再平** 除非用户意图是「平仓并停止 / 紧急停止」且该命令已持久化为 `close_in_progress`。

因此平仓命令也必须先落库：`close_intent=in_progress`。恢复时若该标志为真，允许继续 reduce-only 平仓（这是完成已发出的人工/策略 CLOSE，不是新开仓）。

### L. 本地数据库损坏

无法信任意图。进入 RECOVERY，只读查询交易所，UI 提示从备份恢复。自动备份：周期性复制 SQLite 到 volume（或 `.bak`）。**未实现前**这是运维要求。

若库可读但 WAL 半截：用 SQLite 恢复流程；失败则同损坏。

### M. 本地与交易所不一致

永远以交易所为准，写审计，进 RECOVERY，禁止开仓。方向相反时必须人工。

其它币种出现持仓：RECOVERY + 告警，不自动处理。

## 3. 人工介入清单

必须人工：

- 本地 LONG vs 交易所 SHORT（或相反）
- 帐户出现非配置币种仓位
- 数据库损坏
- estop 后要重新启动
- UNKNOWN 超过查询上限仍无法解释
- 交易所持续不可达超过阈值（阈值 PHASE 2 再定）

可以自动：

- 正常重启且状态一致
- UI 崩溃
- WS 闪断后 snapshot 成功
- 本地仓位过期但交易所 FLAT（改为 FLAT）
- 本地 FLAT 但交易所有仓（改为有仓，保持，等待 CLOSE 或人工平仓）

## 4. 日志与审计

每次状态迁移、每次拒绝的信号、每次 Guard 失败、每次查询 UNKNOWN，写 `system_events` 与 `audit_logs`。审计不可被策略进程写入。
