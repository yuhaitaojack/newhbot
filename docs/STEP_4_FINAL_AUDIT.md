# STEP 4 FINAL AUDIT

**状态：本审计完成并停止。** 未进入 STEP 5。未打开 `EXECUTION_ENABLED`。未发送真实订单。  
**日期：** 2026-09-03  
**性质：** 源码审查 + 非交易测试。不以 live 下单补覆盖。

标记：

- **VERIFIED**：源码路径已核对，且有非交易测试（或此前 STEP 4 live 只读已跑通）
- **NOT VERIFIED**：当前只读约束下未覆盖；禁止为验证而启动真实交易
- **BLOCKED**：按规则停止 / 本 STEP 禁止做的事

**是否自动进入下一阶段：否。**

---

## 本审计修复的必须项

审计发现两处会把“未知”写成 **FLAT** 的安全缺口，已做最小修复（无大规模重构）：

1. `PositionRepository.get()` 在无行时插入 `local_mirror` FLAT。`GET /api/status` 在 Worker 查询前调用它；查询失败后 `_open` 拒绝路径上的 `commit()` 会把假 FLAT 落库。  
   **修复：** `get_or_none()` 只读；失败且无行时展示 `UNKNOWN` / `source=unsynced`，不写库。`start()` 若同步失败则进入 Recovery，不开仓。
2. 未认证 / 账户查询失败时，Adapter 把空仓映射为 **FLAT**，且 `worker_state` 可仍为 READY（`_refresh_from_connector` 会清掉 connect 时的 recovery 说明）。Backend 会把该 FLAT `upsert` 成 `exchange_mirror`。  
   **修复：** 只读且未认证、或 `account_read` 失败时，`get_position`/`get_positions` 抛错，Worker 为 **RECOVERING**，不宣称 FLAT。

非交易测试：**Backend 48 passed**；**Worker 60 passed, 3 skipped**（docker / 无本地 hummingbot，未为审计启动 live）。

---

## 1. live snapshot → Worker → Backend → SQLite mirror

**VERIFIED**（成功路径源码 + 此前 live 只读收口；本轮未再连主网）

```
Connector rest_snapshot / account_positions
  → HyperliquidExecutionAdapter.get_position
  → Worker GET /rpc/position
  → HttpExecutionClient.get_position
  → GET /api/status 或 TradingController._sync_exchange_mirror
  → PositionRepository.upsert_mirror (unique symbol, source=exchange_mirror)
  → SQLite positions
```

- `GET /api/status` 仅在 Worker 查询**成功**后 `upsert_mirror` + `commit`。
- `account_snapshots` / `system_events` position 事件仍只在 Controller `_sync_exchange_mirror`（start / submit / 开仓前成功查询）。status 本身不写这两张表。
- 未新建第二套 REST / tracker。

---

## 2. Exchange Truth > SQLite

**VERIFIED**

- Guard 用本次 Worker 快照的 `exchange_side`，不以 SQLite 覆盖交易所。
- SQLite 仅 mirror / 审计；`positions.source` 成功路径为 `exchange_mirror`。
- 查询失败：不 `upsert`，不覆盖已有 `exchange_mirror`。
- 无行且失败：响应 `UNKNOWN` / `unsynced`，不把 SQLite 假 FLAT 当成交易所真相。
- 开仓前若查询成功，先 `_sync_exchange_mirror` 再读 local，避免“无行 = 假 FLAT”或“无行卡住但交易所已确认 FLAT”。

---

## 3. 查询失败是否误写 FLAT / 覆盖 mirror

**VERIFIED**（修复后；非交易测试）

| 场景 | 行为 |
| --- | --- |
| 已有 `exchange_mirror`，Worker 失败 | 保留原行，不覆盖 **VERIFIED** |
| 尚无行，Worker 失败 | 不插入；status=`UNKNOWN`/`unsynced`；`GET /api/positions` 为空 **VERIFIED** |
| `start()` 同步失败 | Recovery，不进 RUNNING **VERIFIED** |
| 未认证空仓 | Worker 不返回 FLAT，503/`LookupError` **VERIFIED**（单测） |
| 覆盖已有 mirror | 仅成功 `upsert_mirror` **VERIFIED** |

---

## 4. positions mirror 幂等

**VERIFIED**

- `positions.symbol` unique（模型 + `ix_positions_symbol`）。
- `upsert_mirror` 按 symbol 更新同一行，不 insert 第二条。
- 此前 live 两次 `GET /api/status` 仍 1 行；本轮单测 `test_status_upserts_single_exchange_mirror_row`。

fills：`exchange_fill_id` unique + `FillRepository.add` 去重。live fill **NOT VERIFIED**。

---

## 5. Recovery / UNKNOWN / exchange disconnected 禁止新开仓

**VERIFIED**（Guard + Controller；live 异常 Recovery 样本仍 NOT VERIFIED）

- `RECOVERY` → 禁止开仓。
- `exchange_connected=false`（查询异常会把 ready 打成 false）→ 禁止。
- `exchange_side` 或 `local_side` 为 `UNKNOWN` → 禁止（检查已提前到 FLAT 判断之前）。
- `start()` 拿不到 mirror → Recovery。
- Worker 未认证 / 账户查询失败 → `RECOVERING`，`is_ready()` 为 false。

live 人为制造 UNKNOWN 进 Backend Recovery：**NOT VERIFIED**（禁止为此下单或断密钥重连主网）。

---

## 6. Backend 不 import hummingbot

**VERIFIED**

- `backend/app` 无 `import hummingbot` / `from hummingbot`。
- `test_backend_and_strategy_do_not_import_hummingbot` 仍约束该边界。
- `HttpExecutionClient` 只打 Worker HTTP。

---

## 7. 真实交易写操作只经 TradingController

**VERIFIED**（产品路径）

- API：`/trading/start|stop|close*|emergency-stop|signal` 全部进 `TradingController`。
- `place_order` / `cancel_order` 仅 Controller `_submit` / cancel helpers 调用 `ExecutionClient`。
- Strategy stub 只返回信号，不 import execution。
- Frontend 无 Worker `/rpc/place`。
- Worker `/rpc/place_order` 仍存在，供 Controller 使用；compose 仅 `expose` 8001，不对外发布。本 STEP `EXECUTION_ENABLED=false` 时 factory 直接拒绝进程启动。

---

## 8. ReadOnlyGuard + disable_exchange_write_loops + EXECUTION_ENABLED=false

**VERIFIED**（多重保护仍在；本轮未再打 live Guard 表）

1. **Compose / 配置：** `EXECUTION_ENABLED=false`。
2. **Factory：** `execution_enabled=True` 直接 `RuntimeError`，进程起不来。
3. **Adapter：** `execution_enabled=False` 或 connector `read_only` → `ExecutionDisabled`，不调用 inner place/cancel/leverage。
4. **ReadOnlyGuard：** 拦截 buy/sell/`_place_order`/cancel/leverage 等。
5. **disable_exchange_write_loops：** 认证路径在 `start_network` 前打在 raw 实例上（lost-order 内循环绕过 Guard）。本审计改为 **未认证 instantiate 同样 patch**，避免只靠 `trading_required=False`。

本轮 **0** 真实交易所写。live Guard 拦截表见既有 STEP 4 auth 报告，本审计不重复连主网。

---

## 9. 是否出现第二套订单 / 持仓 / fill / reconciliation 状态机

**VERIFIED 无第二套生产状态机**

- 生产 Adapter **不** import `state_store` / `reconciliation` / `quantization` / `instrument_meta`。
- `state_store.py`、`reconciliation.py` 仅测试/遗留模块，不在 factory 运行时路径。
- 仓位真相：Connector `account_positions` / clearinghouse 映射。
- 订单真相：Connector `in_flight_orders`（**不是**全市场挂单簿）。
- Backend SQLite 是 mirror + 审计，不是第二套交易所账本。

---

## 10. account_snapshots / audit_logs / system_events

**NOT VERIFIED**（只读收口故意未走 start/submit；本审计不为验证而开交易）

| 表 | 写入点 | 本审计 |
| --- | --- | --- |
| `positions` | status 成功 upsert；Controller `_sync_exchange_mirror` | 成功路径此前 live **VERIFIED**；失败不写 FLAT 本轮单测 **VERIFIED** |
| `account_snapshots` | 仅 `_sync_exchange_mirror` | **NOT VERIFIED** live |
| `audit_logs` | start/stop/close/estop/settings/signal reverse | **NOT VERIFIED** live |
| `system_events` | Recovery/bootstrap/position emit | position 同步事件 **NOT VERIFIED** live（bootstrap 事件此前有） |

---

## 汇总

### VERIFIED

- 成功 mirror 路径（源码 + 既有 live FLAT 收口）
- Exchange > SQLite（失败不覆盖；无行不假 FLAT）
- positions 幂等（unique + upsert）
- Recovery / UNKNOWN / disconnected 禁止开仓（Guard + start 同步失败）
- Backend 零 hummingbot import
- 写单只经 TradingController（产品路径）
- 三重只读锁仍有效；factory 拒绝 `EXECUTION_ENABLED=true`
- 无第二套生产 tracker
- 本审计 **0** 真实订单

### NOT VERIFIED

- live LONG / SHORT / foreign 持仓
- Connector `in_flight_orders` ≠ 交易所全量挂单
- fills tracker ≠ 全历史成交
- `account_snapshots` / `audit_logs` / position `system_events` 的 live 写入
- live 查询失败进入 Backend Recovery 的现场样本（单测已覆盖）

### BLOCKED

- STEP 5
- `EXECUTION_ENABLED=true`
- 任何真实 place / cancel / leverage
- 为补审计覆盖而启动真实交易

### 是否存在必须修复的问题

**审计时：有（假 FLAT）。本轮已修。当前：无未修必须项。**

### STEP 4 是否可以正式关闭

**可以关闭。** 核心 live 只读闭环此前已跑通；本审计堵住“失败/未认证写成 FLAT”的缺口，并用非交易测试锁住。剩余 NOT VERIFIED 项不得用真实交易去补。

---

## 停止

不开始 STEP 5。不打开 `EXECUTION_ENABLED`。不发送真实交易请求。
