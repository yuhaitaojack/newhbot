# STEP 4 收口报告 — live Worker snapshot → Backend → SQLite

**状态：本收口完成并停止。** 未进入 STEP 5。未发送真实订单。`EXECUTION_ENABLED=false`。  
**日期：** 2026-09-02  
**Hummingbot：** `hummingbot/hummingbot:version-2.16.0`  
**性质：** READ-ONLY LIVE（用户明确要求继续使用已提供的 credential）

标记：

- **VERIFIED**：本会话实际跑通
- **NOT VERIFIED**：未在该条件下观察到
- **BLOCKED**：按规则停止
- **N/A**：本 STEP 禁止做的事

**是否自动进入下一阶段：否。**

报告用语：authenticated credential supplied。不写 secret。

---

## 结论

真实 Hyperliquid 账户快照已经走完现有生产路径：

Connector → Worker `/rpc/position` → Backend `GET /api/status` → `PositionRepository.upsert_mirror` → SQLite `positions`（`source=exchange_mirror`）

未新建 tracker / REST / 对账状态机。未 place / cancel / leverage。

当前账户 **BTC-USD = FLAT**（认证后交易所无仓，不是把查询失败当成 FLAT）。

---

## A. authenticated live snapshot

**VERIFIED**

| 项 | 结果 |
| --- | --- |
| Worker `POST /rpc/connect` | ok |
| `worker_state` | READY |
| `recovery_reason` | null |
| `EXECUTION_ENABLED` | false |
| BTC-USD | **FLAT** size `0` |
| 非零仓位列表 | 0（无 foreign） |
| Connector `in_flight_orders` / adapter open orders | 0（**tracker，≠ 全市场挂单**） |
| Connector fills tracker | 0（≠ 全历史成交） |

LONG / SHORT / foreign live：**NOT VERIFIED**（账户当前无仓；禁止开仓制造）。

---

## B. Worker → Backend 数据路径

**VERIFIED**

```
GET /api/status
  → HttpExecutionClient.get_position("BTC-USD")
    → Worker GET /rpc/position
      → Adapter/Bridge/Connector
        → upsert_mirror(..., source=exchange_mirror)
```

- 第一次 `/api/status`：`position.side=FLAT`，`source=exchange_mirror`，`system_state=STOPPED`，`worker_ready=true`，`sync_status=LIVE`
- 未调用 `POST /api/trading/start`（避免 `trading_enabled=true` 与 `stop` 时的 cancel 尝试）
- 未调用 `POST /api/trading/signal`

---

## C. PositionGuard

用本轮 live 快照求值（未下单）：

| 输入 | 结果 |
| --- | --- |
| STOPPED + 交易所 FLAT | 禁止开仓（`system is STOPPED`）**VERIFIED** |
| RUNNING + FLAT + 已连接 | Guard 允许（执行层仍会因 EXECUTION_ENABLED=false / ReadOnlyGuard 拒单）**VERIFIED** |
| Worker 断开 `exchange_connected=false` | 禁止（`exchange connection unavailable`）**VERIFIED** |
| RECOVERY | 禁止开仓 **VERIFIED** |
| 反手 | 禁止 **VERIFIED** |

真实 Connector 状态进入 Guard 输入：**VERIFIED**（FLAT）。本轮 **没有** POST signal，因此没有 Worker `place_order`。

---

## D. Recovery

Backend bootstrap：worker 可达 → `STOPPED`。  
connect 后 Worker `READY`，`recovery_reason=null`。  
未进入 RECOVERING。live 异常 Recovery 样本：**NOT VERIFIED**（未人为制造 UNKNOWN/查询失败进 Recovery 状态机）。  
RECOVERY 禁止开仓规则：**VERIFIED**（Guard）。

---

## E. SQLite live mirror

库：`data/step4_live_mirror.db`（gitignore `*.db`）

| 表 | 本轮 |
| --- | --- |
| `positions` | **1 行** `BTC-USD` / `FLAT` / size `0` / `source=exchange_mirror` **VERIFIED** |
| `account_snapshots` | 0 — GET `/api/status` **不写**该表。写入在 `_sync_exchange_mirror`（start/submit）。**NOT VERIFIED**（故意不调 start） |
| `audit_logs` | 0 — status 不写 audit **NOT VERIFIED** |
| `system_events` | 1 行 bootstrap，不是 position sync **NOT VERIFIED**（position 事件同样只在 `_sync_exchange_mirror`） |

---

## F. Exchange truth > SQLite

1. 成功路径：SQLite 来自本次 Connector FLAT，`source=exchange_mirror` **VERIFIED**  
2. Worker 停止后再 `GET /api/status`：SQLite **仍是** `FLAT` + `exchange_mirror`（**未改写、未另造一行**）；`worker_ready=false` **VERIFIED**  
3. 失败时开仓：`exchange_connected=false` 禁止 **VERIFIED**  
4. “无认证空仓 = FLAT”：本轮是 **认证后** 的 FLAT，不是未认证空返回 **VERIFIED**  
5. 失败且库中尚无 mirror 时 status 会插入 `local_mirror` FLAT：代码缺口仍在；本轮先有 live mirror，故未踩到。该缺口 **未在本轮修复**（未大规模重构）

---

## G. audit

GET `/api/status` 不写 `audit_logs`。**NOT VERIFIED**（只读收口未走 start）。  
最小接线（未做）：status 成功时写 `system_events`。

---

## H. 重复同步 / 幂等

两次 `GET /api/status` 后 `positions` **仍 1 行** **VERIFIED**。  
fills unique：无 live fill，前置单测仍有效。

---

## I. 查询失败安全

Worker down 后 status 使用已有 `exchange_mirror`，不覆盖。Guard 在断开时禁止开仓。**VERIFIED**  
未把失败修成新的假 FLAT（已有 live 行）。

---

## J / K / L / M

| 项 | 标记 |
| --- | --- |
| ReadOnlyGuard | 本轮未再打 buy/sell；`EXECUTION_ENABLED=false`；未 place **VERIFIED 无写操作** |
| lost-order disable | 认证 connect 仍走既有 `disable_exchange_write_loops`（代码路径）；本轮未重复打印 Guard 拦截表。上一轮 live **VERIFIED** |
| EXECUTION_ENABLED | **false VERIFIED**（Worker `/health`） |
| 真实交易写操作数量 | **0 VERIFIED** |

---

## 汇总

| 项 | 标记 |
| --- | --- |
| A live snapshot | **VERIFIED**（FLAT） |
| B Worker → Backend | **VERIFIED** |
| C PositionGuard | **VERIFIED**（用 live FLAT） |
| D Recovery live 异常 | **NOT VERIFIED** |
| E positions mirror | **VERIFIED** |
| E account_snapshots / audit | **NOT VERIFIED** |
| F Exchange > SQLite（成功+断开后不覆盖） | **VERIFIED** |
| G audit | **NOT VERIFIED** |
| H 幂等 | **VERIFIED** |
| I 失败不开仓 | **VERIFIED** |
| J/K/L | Guard/disable 既有；本轮 enabled=false |
| M 写操作 | **0** |
| STEP 5 | **未进入** |
| LONG/SHORT/foreign/真实挂单全量 | **NOT VERIFIED** |

---

## 停止

不开始 STEP 5。不打开 `EXECUTION_ENABLED`。不发送真实交易请求。
