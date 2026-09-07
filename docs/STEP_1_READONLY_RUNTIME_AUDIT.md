# STEP 1 — READ-ONLY RUNTIME AUDIT

**日期：** 2026-09-03  
**性质：** 只检查。未执行任何交易。未重启服务。未修改配置。未 git commit。  
**禁止项本轮均未调用：** `POST /rpc/place_order`、`POST /api/trading/signal`、`POST /api/trading/close-and-stop`、cancel、set_leverage。

**STEP_1_RESULT = FAIL**

FAIL 不是因为核查没做完，而是因为运行态仍武装，且交易所仍有真实多仓。

---

## 1. 实际进程 / 端口 / 启动命令

| 组件 | 状态 | 端口 | 证据 |
| --- | --- | --- | --- |
| frontend | **未运行** | 5173 / 8080 无监听 | `GET http://127.0.0.1:5173/` 失败；无 vite 进程 |
| backend | **在跑** PID 11244 | `127.0.0.1:8000` | `"C:\Python314\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000`；启动 **2026-09-03 20:50:11**；父进程 19400 已不在 |
| execution-worker | **在跑** 容器 `newhbot-step5-oneshot-worker` | `127.0.0.1:8001` | 镜像 `newhbot-execution-worker:step4`；entrypoint `/opt/conda/envs/hummingbot/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8001`；**Started 2026-09-03T12:52:13Z** |

一开一平脚本已于 `12:46:14Z` 以 exit 2 结束，当时打过 `WORKER_STOPPED`。当前 Worker 是 **12:52Z 再次拉起的武装容器**，不是那个已退出的监控进程。

Bind mount：`E:/yu_cursor_workspace/newhbot/execution-worker/app -> /app/app (ro)`。

---

## 2. 是否加载了最新代码

### 2.1 reduce_only 是否跳过 entry min-notional

**磁盘 + 容器内文件：是。运行时未再用一笔单去验证。**

容器内只读读到：

- `SKIP_MIN_NOTIONAL_REDUCE_ONLY True`
- `if not request.reduce_only and qty * px < min_notional`

该文件 mtime **20:41:43**。当前 Worker 在 **20:52:13** 启动并 bind-mount 该目录，因此 **当前进程 import 的是带 skip 的代码**。

历史反证（`12:39:46Z` 那笔 CLOSE）：`reduce_only=true` 仍返回 `notional 9.67707 below minimum 10`。那是更早的武装进程，不能证明当前进程还会同样拒单。

### 2.2 CLOSE 被拒是否 `ok=false` 并进 RECOVERY

**当前源码：是。当前 backend 进程是 20:50:11 启动的，晚于文件 mtime 20:41:48，因此已加载该分支。历史 12:39 那笔没有走这个分支。**

源码：

```309:315:backend/app/controllers/trading_controller.py
        if order.status == OrderStatus.REJECTED:
            settings.close_intent = None
            await self._recovery.enter_recovery(
                session, f"close_rejected:{order.error_message or 'execution worker rejected order'}"
            )
            await session.commit()
            return {"ok": False, "reason": order.error_message or "close order rejected", "cloid": order.cloid}
```

历史证据（12:39 CLOSE）：

- 订单 `0x9b81cf27d36e432da84bff99fe3e59c9` status=`REJECTED`
- 事件只有 `order status REJECTED`，**没有** `close_rejected`
- `last_signal_reason` 仍是 **`closed`**（当时 API 把 REJECTED 当成成功 CLOSE）
- 当时系统仍是 RUNNING；**20:50 重启后**才因 OPEN 单 UNKNOWN 进入 RECOVERY

仓库测试里 **没有** `close_rejected` / reduce-only skip 的回归断言。

---

## 3. Health / status / 真实仓位 / 挂单

### Worker `GET /health`

```json
{"status":"ok","mode":"hyperliquid","connected":true,"ready":true,"worker_state":"READY","execution_enabled":true,"trading_pair":"BTC-USD","ws_connected":true,"sync_status":"LIVE","hummingbot_version":"v2.16.0","recovery_reason":null,"foreign_symbols":[]}
```

### Backend `GET /api/status`（摘要）

| 项 | 值 |
| --- | --- |
| `system_state` | **RECOVERY** |
| `trading_enabled` | **true** |
| `estop` | false |
| `last_signal` | CLOSE / reason `closed` |
| position | **BTC-USD LONG 0.00013 @ 78352**，`source=exchange_mirror` |
| last_order | CLOSE SELL REJECTED，`notional 9.67707 below minimum 10` |
| equity / available / margin_used | ≈ 15.07 / 11.67 / 3.40 |

### Worker 真实仓位（GET only）

- `GET /rpc/position?symbol=BTC-USD` → LONG `0.00013` entry `78352.0`
- `GET /rpc/positions` → 仅这一笔，无 foreign

### 挂单（GET only）

- `GET /rpc/open_orders` → `[]`
- 官方 `GET /rpc/open_order_precheck` → `VERIFIED`，BTC-USD = 0，其它 coin = 0

### 本地订单

| cloid | 方向 | reduce_only | 状态 |
| --- | --- | --- | --- |
| `0x843ccebd016d4445b4877c5a7f458ca0` | BUY OPEN | false | **UNKNOWN**（`get_position failed: All connection attempts failed`） |
| `0x9b81cf27d36e432da84bff99fe3e59c9` | SELL CLOSE | true | **REJECTED** |

### 事件（`GET /api/events`）

| 时间 (UTC) | 事件 |
| --- | --- |
| 12:38:33 | bootstrap STOPPED |
| 12:38:34–12:38:44 | STARTING → SYNCING → RUNNING（user_start）；当时仓位 FLAT |
| 12:39:23 | OPEN `0x843ccebd...` status OPEN；仓位 LONG 0.00013 |
| 12:39:52 | CLOSE `0x9b81cf27...` status REJECTED；仓位仍 LONG 0.00013 |
| 12:50:20 | RUNNING → RECOVERY（`unconfirmed_place`）；OPEN 标 UNKNOWN；`unresolved_orders_on_boot` |

---

## 4. 开关与状态

| 项 | 值 |
| --- | --- |
| 容器 `EXECUTION_ENABLED` | **true** |
| backend health `execution_enabled` | **true** |
| `trading_enabled` | **true** |
| `system_state` | **RECOVERY** |
| 重启原因 | `unconfirmed_place` → `unresolved_orders_on_boot` |
| Compose / Dockerfile 默认 | 未改（本轮未动文件） |

RECOVERY 期间按产品规则禁止新开仓。当前仍武装；CLOSE 路径是否放行取决于 Controller。本轮未调用任何写接口。

---

## 5. 是否需要平仓（未发任何订单）

**需要。** 交易所 BTC-USD **仍是 LONG 0.00013**，挂单为 0。这是 STEP 5 OPEN 留下的真实仓，不是镜像假数据。

本轮 **没有** 发送 CLOSE / signal / place_order。

---

## 结论

FAIL 条件已同时成立：

1. 真实仓位未平。
2. 一开一平结束后，武装 Worker **又被拉起来**，`EXECUTION_ENABLED=true`。
3. 历史 CLOSE 被拒时没有 `ok=false` / `close_rejected`；那笔行为已写进 SQLite。当前代码修了，但 **没有用实盘再验证**。

---

## 下一步建议（须另开明确授权）

1. **不要**再开新仓，不要点 UI Start，不要再跑 oneshot。
2. 若要处理遗留多仓：单独授权 **一笔 reduce-only CLOSE**，走 TradingController；OPEN 的 UNKNOWN 只查询、不重发。
3. 平仓前先确认当前 Worker 已加载 skip min-notional 的 reduce_only 路径；CLOSE 若再 REJECTED，应看到 `ok=false` 且保持 RECOVERY。
4. 结束后立刻把运行时 `EXECUTION_ENABLED` 关掉并停掉该容器；**不要**改 Compose / Dockerfile 默认值。
5. 未授权平仓之前，维持现状、不再发单。

本文件不含 API secret / 私钥。
