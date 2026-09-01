# 交易与系统状态机

详细恢复场景见 `docs/RECOVERY_DESIGN.md`。执行幂等见 `docs/EXECUTION_DESIGN.md`。

## 1. 系统状态

```
STOPPED
   │ start
   ▼
STARTING
   ▼
CONNECTING          ← WS/REST 连不上：保持；超时 → ERROR
   ▼
SYNCING             ← 拉 meta、trading rules、账户、持仓、挂单
   ▼
RECONCILING         ← 对比 SQLite vs Hyperliquid
   ├─ 一致且上次意图为运行 → READY → RUNNING
   ├─ 有 UNKNOWN 订单 / 仓位方向冲突 / 多币种仓 → RECOVERY
   └─ 本地库损坏 → RECOVERY（人工）
RUNNING
   ├─ 用户停止 → 撤开仓单（不平仓）→ STOPPED
   ├─ 平仓并停止 / 紧急停止 → 见控制命令
   ├─ 断连 → CONNECTING（禁止开仓）
   └─ 不一致 → RECOVERY

RECOVERY            ← 禁止 LONG/SHORT
   ├─ 对账完成且无 UNKNOWN → READY（若用户意图仍是运行则 RUNNING）
   └─ 无法自动解释 → 保持 RECOVERY，等人工

ERROR               ← 禁止开仓；可人工紧急停止 / 平仓
READY               ← 已同步、未跑策略循环
```

### 自动进入 RUNNING 的条件（必须全部满足）

- 交易所可查询
- 无 UNKNOWN 订单
- 本地与交易所仓位同为 FLAT，或同方向同币种（允许继续持有，**不得**因重启而加仓）
- 无「账户上其它币种持仓」
- 持久化的用户意图是 `running=true` 且非紧急停止
- 不在人工锁定

否则：STOP / RECOVERY，不要自作主张开跑。

## 2. 仓位视图（Position Guard）

本地与交易所各自为：`FLAT` | `LONG` | `SHORT` | `UNKNOWN`

开仓允许 **仅当**：

```
local == FLAT
AND exchange == FLAT
AND no open orders on the configured pair (except we will cancel leftovers first)
AND no order in UNKNOWN
AND system in RUNNING
AND signal in {LONG, SHORT}
AND pair == settings.trading_pair
```

禁止开仓（进入 RECOVERY 或直接拒绝信号）：

| 本地 | 交易所 | 动作 |
| --- | --- | --- |
| FLAT | LONG/SHORT | 禁止开仓；以交易所为准同步；保持/进入 RECOVERY 至一致 |
| LONG/SHORT | FLAT | 禁止开仓；以交易所为准改为 FLAT；查是否有未完成平仓 |
| LONG | SHORT | 禁止一切开仓；RECOVERY 人工 |
| SHORT | LONG | 同上 |
| * | * 且订单 UNKNOWN | 禁止新开仓 |
| * | 连接失败 | 禁止开仓 |
| * | Controller ERROR | 禁止开仓 |
| 任何非 FLAT | 任何 | 拒绝新的 LONG/SHORT |

反向信号在有仓时 = `HOLD`（记录审计「ignored reverse」），**不是**平仓。

## 3. 订单状态（我方）

```
INTENT_RECORDED → SUBMITTING → OPEN → PARTIAL → FILLED
                              ↘ REJECTED / CANCELED
                     ↘ UNKNOWN（超时、无回报、进程崩溃在提交后）
```

UNKNOWN 的唯一合法出口：用 `cloid` 调 HL `orderStatus`，并交叉 `openOrders` + `clearinghouseState`。

禁止：UNKNOWN 时再用新 cloid 下同样意图的单。

## 4. 控制命令

| UI | 行为 |
| --- | --- |
| 启动 | 持久化 running=true → 走 STARTING… 状态机 |
| 停止 | running=false；撤销未成交开仓单；**不平仓**；策略循环停 |
| 平仓并停止 | CLOSE 流程 → 确认 FLAT → STOPPED |
| 平仓并继续 | CLOSE 流程 → 确认 FLAT → 保持 RUNNING（下一根信号才可能开仓） |
| 紧急停止 | 撤销所有挂单 → 尽可能 reduce-only 平仓 → running=false、estop=true；恢复需人工取消 estop |

紧急停止失败（无法确认 FLAT）：留在 RECOVERY，禁止开仓。

## 5. 策略信号在 RUNNING 中的处理

```
HOLD  → 忽略
LONG/SHORT → Guard → 通过才下开仓单；失败只记审计
CLOSE → 无仓则忽略；有仓则 reduce-only 平仓
```

策略崩溃：记事件，持仓不动，不自动平仓（除非用户之后点平仓）。策略死循环：Runtime 超时杀掉进程，同上。
