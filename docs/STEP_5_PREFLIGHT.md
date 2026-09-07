# STEP 5 PRE-FLIGHT AUDIT

**状态：预检完成并停止。** 未执行 STEP 5。未打开 `EXECUTION_ENABLED`。未发送真实订单。  
**日期：** 2026-09-03  
**性质：** 交接文档 + 源码状态审查。不改核心架构。不增加第二套状态机。不引入 Hummingbot Strategy V2 / Executor / Controller。

**STEP 4 CLOSED：确认。** 依据 `docs/STEP_4_FINAL_AUDIT.md`。

**是否自动开启实盘：否。** 本文件不是实盘授权。

---

## STEP 4 CLOSED：确认

STEP 4（认证只读 live snapshot → Worker → Backend → SQLite `exchange_mirror` + FINAL AUDIT 假 FLAT 修复）已正式关闭。

当前生产路径仍为：

```
Web UI → Backend API / SQLite → TradingController → PositionGuard
  → HttpExecutionClient → Execution Worker
    → HyperliquidExecutionAdapter
      → ReadOnlyHummingbotBridge → ReadOnlyGuard
        → HyperliquidPerpetualDerivative v2.16.0
```

默认：`EXECUTION_ENABLED=false`。Factory 在 `true` 时拒绝启动。Adapter / Guard / `disable_exchange_write_loops` 拦截写。Backend 不 import hummingbot。

---

## STEP 5 目标（最小范围）

STEP 5 的唯一目标是：**在用户单独确认后，证明现有架构能经 TradingController 发出一笔真实 Hyperliquid 永续订单，并安全收回。**

包含：

1. 受控解除「完全禁止写」中**仅下单所需**的那一层（见下文安全边界）。
2. 一笔最小名义开仓（建议 ≥ $10 `MinTradeNtl`，单币种、单方向）。
3. 同一路径 `CLOSE` / 一键平仓确认回到交易所 FLAT。
4. SQLite `orders` / `fills` / `positions` / `audit_logs` / `account_snapshots` 跟随交易所（Exchange > SQLite）。
5. 确认：UNKNOWN 不重发、无自动反手、有仓禁开、Recovery 禁开、`buy()`/`sell()` 仍禁用、lost-order 自动撤单仍禁用。

**明确不包含（留给 STEP 5+ / 后续指令）：**

- 5 分钟 K 线 RSI/ATR 策略实现与自动循环
- 自动改杠杆到 3x（Controller 目前**不调用** `set_leverage`）
- 全市场挂单簿、全历史 fill 的第二套 REST
- Hummingbot Strategy V2 / Controller / PositionExecutor
- 多币种、对冲、自动反手
- 把 Compose 默认改成实盘常开

用户此前记录的策略（阴线 RSI7>45 开多 / 阳线 RSI7<55 开空、全仓 3x、ATR×2 止损、1:1.5 止盈）是 **STEP 5+**，不是本 STEP 最小闭环。

---

## 检查：STEP 5 是否涉及真实下单

**是。** 只读闭环已在 STEP 4 完成。STEP 5 若执行，必然触及真实 `place` / 可能 `cancel` / 平仓时的 reduce-only。`set_leverage` 不是最小闭环所必需。

本预检 **不执行** 这些调用。

| 步骤 | 是否真实写 | 本预检 | 正式 STEP 5 前必须再确认 |
| --- | --- | --- | --- |
| 读文档 / 列缺口 | 否 | 本轮 | — |
| 写「armed」代码闸门（仍默认 false） | 否（代码准备） | **未做**；需下一步指令 | 不得顺手打开 env |
| 非交易单测（enabled=false 仍拒绝） | 否 | 未跑新闸门（闸门未写） | — |
| 只读再确认 FLAT / 余额 / 无 foreign | 私有查询，非下单 | 未跑 | 主网私有 API 需会话确认 |
| `EXECUTION_ENABLED=true` | 进程级解除 DRY_RUN | **禁止自动** | **单独一句话确认** |
| 一笔最小开仓 | **是** | **禁止** | **单独一句话确认「允许发送这一笔」** |
| 平仓 | **是** | **禁止** | 含在同一笔测试授权内，或再确认 |
| 改杠杆 | 是 | **禁止** | 最小闭环默认不做 |
| 策略自动循环 | 会连续下单 | **禁止** | STEP 5+ |

---

## 安全边界（必须保留到正式执行测试前）

下列保护 **现在必须全部保持**。在用户明确授权「可以发这一笔」之前，不得改 Compose / Dockerfile / `.env` 为 `EXECUTION_ENABLED=true`。

| 层 | 现状 | 正式 STEP 5 时 |
| --- | --- | --- |
| Compose `EXECUTION_ENABLED=false` | 保留 | 仅临时覆盖，测完改回 false |
| Dockerfile `ENV EXECUTION_ENABLED=false` | 保留 | 同上 |
| Factory：`true` 则 `RuntimeError` | **硬拒绝进程启动** | 必须改闸门，否则无法测写；改完仍默认 false |
| Adapter：`read_only` 或 `enabled=false` → REJECTED / ExecutionDisabled | 保留 | enabled 时才 `connector.place` |
| `ReadOnlyGuard`（含 `_place_order`） | live Bridge 始终包裹 | **不能整段拆掉**；buy/sell 必须永远禁 |
| `disable_exchange_write_loops` | 认证/未认证都 patch | **`_cancel_lost_orders` 必须保持 no-op**（否则 HB 内循环绕过 Guard 真撤单） |
| 同一 patch 当前也挡住 `_place_order` | 与 `hummingbot_place.place_with_injected_cloid` **冲突** | 见「缺失项」 |
| Worker 仅 `expose 8001` | 保留 | 保留 |
| Backend 不 import hummingbot | 保留 | 保留 |
| 写单只经 TradingController | 保留 | **禁止脚本直打 Connector** |
| 策略只出四态信号 | 保留 | 最小 STEP 5 用 `POST /api/trading/signal`，不用 V2 |

**关键结论：** 仅把 `EXECUTION_ENABLED` 设为 true **不足以**下单。Factory 会拒绝启动；即使改掉，Guard + write-loop patch 仍会拦截 `_place_order`。正式 STEP 5 需要一次**有意的、可回滚的武装路径**，而不是关保护。

建议的武装语义（实现留给下一步，本预检不改代码）：

- `buy()` / `sell()` 永远禁止（避免第二套 MD5 cloid）。
- lost-order 自动 cancel 永远 disable。
- 仅当 `EXECUTION_ENABLED=true` **且** 请求来自 Worker RPC（Controller）时，允许 `place_with_injected_cloid` 调用**未 Guard 掉的** raw `_place_order`。
- 默认进程、默认 Compose、默认镜像仍为只读。

---

## 前置条件

1. 用户在**当前会话**明确确认：主网或 testnet、允许真实下单、允许的最大名义 / 币种。
2. 账户与 STEP 4 只读账户一致或用户另行指定；密钥只在未跟踪 `.env` / Docker secret。
3. 交易所该币种 **FLAT**，无 foreign 仓，无未跟踪挂单（`in_flight_orders` 空 ≠ 全市场无挂单，开仓前须用认证 snapshot / 账户查询交叉确认）。
4. Worker 认证 READY；Backend `start()` 能写入 `exchange_mirror`；非 Recovery、非 estop。
5. 代码闸门已按上节改完，且 `EXECUTION_ENABLED=false` 时全套测试仍拒绝写。
6. 最小数量满足 Hyperliquid `$10` 名义与 tick/step。
7. 独立 SQLite（不要用乱入的开发库当唯一真相；Compose 默认 `./data/newhbot.db`）。
8. 回滚预案：estop / close-and-stop；测完立刻把 enabled 改回 false。

`AGENTS.md` 仍适用：最多一仓、禁反手、Exchange > SQLite、Recovery 禁开、密钥不进 Git。

---

## 当前缺失项

### 代码闸门（正式 STEP 5 前必须做，本预检不做）

- Factory 仍无条件拒绝 `EXECUTION_ENABLED=true`。
- `ReadOnlyHummingbotBridge.place` / Guard 拦截 `_place_order`。
- `disable_exchange_write_loops` 把 raw `_place_order` 换成 raise，与 `hummingbot_place.py` 互斥。
- 没有「armed connector」：在保留 lost-order no-op 与禁 `buy`/`sell` 的前提下，只放开注入 cloid 的 place。
- 没有经 Controller 的 live 写探针脚本（现有 `step4_*` 均为只读）。

### 配置 / 部署

- `docker-compose.yml` **未**挂 `.env` / Docker secrets；Compose 默认 Worker 无凭证 → 未认证 → 不得视为 FLAT。
- Backend Compose `EXECUTION_MODE=mock` 只是标签；Backend 经 `EXECUTION_WORKER_URL` 打 Worker。不是架构否决，但正式联调应标明 Worker=`hyperliquid`。
- 杠杆：设置项在 SQLite，Controller **从不** `set_leverage`。3x 策略依赖未接线。

### 策略 / 产品

- 仓库策略仍是 `example_strategy` → 只 `HOLD`。
- RSI/ATR **未实现**。最小 STEP 5 不应先做策略。
- K 线数据源未选定（CandlesFactory vs HL WS）。

### 测试 / 数据

- live LONG/SHORT/foreign、全量挂单、全历史 fill、live UNKNOWN：**NOT VERIFIED**（STEP 4 故意未做）。
- `account_snapshots` / `audit_logs` / position `system_events` live 写入：**NOT VERIFIED**。
- 无「最小实盘下单」测试夹具（正确：不得在未授权时写）。

### 已具备（可复用，不必重做架构）

- TradingController `_submit`：先 COMMIT intent，一次 `place_order`，超时 UNKNOWN 不重发。
- PositionGuard：FLAT+FLAT+RUNNING+已连接。
- `hummingbot_place.place_with_injected_cloid`（Fake / stub 已验证；真实 Connector **写路径 NOT VERIFIED**）。
- SQLite schema、唯一 cloid、fill idempotency。
- STEP 4 认证只读 + mirror 路径。

---

## 风险点

1. **误以为改一个 env 就能下单，或改 env 会绕过 Guard。** 当前多层锁是故意的。
2. **为了下单拆掉 `disable_exchange_write_loops`。** lost-order 循环会在 raw `self` 上自动撤单。
3. **脚本直连 Connector / Worker RPC，绕过 Controller。** 违反 `AGENTS.md`。
4. **把 `in_flight_orders=={}` 当成无挂单。** 可能双开或与人工挂单冲突。
5. **同一账户上的 foreign / 网页仓。** live foreign **NOT VERIFIED**；出现则 Recovery，禁止自动平。
6. **主网小账户。** STEP 4 用的是主网认证账户。testnet 未作为默认。名义 <$10 会被拒。
7. **UNKNOWN 后重试 `buy()`。** 会生成新 cloid → 双开。必须沿现有「只查不重发」。
8. **IOC 滑点失败被当成可改 GTC 重试。** 设计禁止（GTC 会留挂单）。
9. **实现 RSI 策略并自动 RUNNING。** 会在未证明单笔路径前连续下单。
10. **引入 Strategy V2 Executor。** 自管 TP/SL、可多 executor，与一仓/信号分离冲突。
11. **测完不把 `EXECUTION_ENABLED` 改回 false。**

---

## 建议的最小执行顺序

**现在停在第 0 步。未获下一指令前不改代码、不改 env、不下单。**

0. **本预检**（完成）。STEP 4 关闭。保护全开。
1. 用户确认最小 STEP 5 =「一开一平」还是还要包含策略 / 杠杆。
2. 用户确认场所（主网 vs testnet）与硬上限（名义、币种、最多 1 笔开仓）。
3. **仅在确认后：** 实现 armed 写路径；默认仍 `EXECUTION_ENABLED=false`；单测证明 false 时仍全拒绝。
4. 只读再确认：认证 READY、BTC-USD（或指定币种）FLAT、无 foreign、权益足够 $10。
5. 用户**再发一句**：「允许发送这一笔真实订单」。
6. `POST /api/trading/start` → `signal LONG` 或 `SHORT`（经 Controller）→ 确认交易所仓与 SQLite mirror → `CLOSE` 或一键平仓 → FLAT。
7. 立即 `EXECUTION_ENABLED=false`，写 `docs/STEP_5_REPORT.md`，停止。不自动做 RSI 策略。

---

## 本轮未做

- 未修改 factory / Guard / Compose / `.env`
- 未打开 `EXECUTION_ENABLED`
- 未 place / cancel / leverage
- 未实现策略
- 未进入 STEP 5 执行

等待下一步指令。
