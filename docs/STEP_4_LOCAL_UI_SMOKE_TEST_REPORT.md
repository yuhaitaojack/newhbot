# STEP 4 — LOCAL UI AND API SMOKE TEST

**日期：** 2026-09-04  
**性质：** 本地默认安全配置冒烟。只读检查 Compose、API、UI。  
**禁止项本轮均未做：** 未点 UI 启动 / 平仓 / 紧急停止；未调用 place_order / close / cancel / set_leverage；未设真实密钥；未改 Compose / Dockerfile / `.env` 默认值；未启动策略循环；未 git commit；未连接 Hyperliquid 实盘（worker `connected=false`，`execution_enabled=false`）。  
**本文件不含** API secret / 私钥。

**STEP_4_RESULT = PASS**

---

## 1. Docker Compose

`docker compose ps`：

| NAME | IMAGE | STATUS | PORTS |
| --- | --- | --- | --- |
| newhbot-frontend-1 | newhbot-frontend | **Up** | `127.0.0.1:8080->80/tcp` |
| newhbot-backend-1 | newhbot-backend | **Up** | `127.0.0.1:8000->8000/tcp` |
| newhbot-execution-worker-1 | newhbot-execution-worker | **Up** | `8001/tcp`（**未**发布到主机） |

`docker ps -a` 仅上述三个容器。没有 `newhbot-step5-oneshot-worker`，没有 `tender_wing`。

环境（容器内读取，非 `.env` 实值）：

| 项 | 值 |
| --- | --- |
| worker `EXECUTION_ENABLED` | **false** |
| worker `/health` `execution_enabled` | **false** |
| worker `connected` | **false** |
| worker `worker_state` | **NOT_READY** |
| backend `EXECUTION_MODE` | **mock** |
| backend `EXECUTION_ENABLED` | **false** |

---

## 2. API（GET only）

### GET http://127.0.0.1:8000/api/health

```json
{"status":"ok","execution_mode":"mock","worker_ok":true,"worker_ready":false,"worker_state":"NOT_READY","execution_enabled":false,"sync_status":"NONE"}
```

### GET http://127.0.0.1:8000/api/status（摘要）

| 项 | 值 |
| --- | --- |
| `system_state` | **STOPPED** |
| `trading_enabled` | **false** |
| `estop` | false |
| position | **FLAT** 0 BTC-USD，`source=exchange_mirror` |
| `worker_state` | NOT_READY |
| `sync_status` | NONE |
| last_order / last_fill / last_signal | null |

### GET /api/orders

`[]`

### GET /api/fills

`[]`

### GET /api/events

一条 bootstrap：`STOPPED → STOPPED` reason `bootstrap`（`2026-09-04T04:45:23`）。

前端 nginx 反代 `GET http://127.0.0.1:8080/api/status` 同样 HTTP 200，body 与 backend 一致。

backend 日志本轮只有 **GET**（`/api/status`、`/api/settings`、`/api/strategy`、`/api/orders`、`/api/trades`、`/api/events`，以及 worker 只读 health/position/balance）。没有 POST place_order / close / cancel / set_leverage。

---

## 3. 前端 http://127.0.0.1:8080

浏览器逐页打开（未点启动 / 停止 / 平仓 / 紧急停止 / Save）：

| 页面 | 结果 |
| --- | --- |
| Dashboard `/` | 加载成功。**STOPPED**，`trading_enabled=false`，FLAT 0 BTC-USD，Worker **NOT_READY**，Last Order/Fill 为 — |
| Settings `/settings` | 加载成功。SQLite 表单：BTC-USD / leverage 3 / ema5break v1 |
| Strategy `/strategy` | 加载成功。ema5break + example_hold；参数 `enabled=false` |
| Orders `/orders` | 显示 `[]` |
| Trades `/trades` | 显示 `[]` |
| Events `/events` | 显示 bootstrap STOPPED 事件 |

首屏会短暂出现 `Loading…`（等 `/api/status` 或列表 GET），约 1–2 秒后渲染数据。这不是卡死。页面无错误横幅。本轮注入的 `error` / `unhandledrejection` 监听为空。

未点任何交易按钮。

---

## 4. 默认安全边界

| 条件 | 结果 |
| --- | --- |
| worker `connected=false` 或未认证 | **通过**（`connected=false`，`ready=false`） |
| worker `execution_enabled=false` | **通过** |
| backend `system_state=STOPPED` | **通过** |
| `trading_enabled=false` | **通过** |
| position=FLAT | **通过**（Compose 使用 `./data/newhbot.db`；worker 未认证，不是 STEP 5 实盘库） |
| 没有真实订单写操作 | **通过** |
| 没有一次性武装 worker | **通过** |
| 主机 `127.0.0.1:8001` | 仍不可达（worker 仅内网） |

---

## 5. 发现的问题

无阻断项。未改代码。

观察（不判 FAIL）：

- Dashboard / 列表页在数据返回前显示 `Loading…`。fetch 失败时目前不会把错误画出来（会一直 Loading）；本轮 fetch 均成功，未触发。
- Dashboard 每 4 秒 GET `/api/status`，backend 随之 GET worker health/position/balance。均为只读，且 worker 未武装、未连接实盘。

---

## 6. 结论

本地默认 Compose 栈可用：三个服务在跑，API 返回 STOPPED / mock / 未武装，UI 能显示同一套数据。安全边界保持。

**STEP_4_RESULT = PASS**
