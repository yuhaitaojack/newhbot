# STEP 5 — LOCAL UI CONTROL FLOW TEST

**日期：** 2026-09-04  
**性质：** 本地 UI 控件接到 backend API。Compose 默认部署。`EXECUTION_MODE=mock`，worker `EXECUTION_ENABLED=false`。未设真实密钥。未点「平仓并继续」。未 git commit。未改 Compose / Dockerfile / `.env` 默认值。  
**本文件不含** API secret / 私钥。

**STEP_5_RESULT = PASS**

---

## 0. 前端修复（测试前）

原 UI 不满足本 STEP 的交互要求：

- fetch 失败会一直 `Loading…`，且 `command()` 未 catch，错误进 console
- 按钮执行中可重复点击

只改前端：

| 文件 | 改动 |
| --- | --- |
| `frontend/src/api.ts` | 网络/HTTP 失败变成可读错误 |
| `frontend/src/pages/DashboardPage.tsx` | 成功/失败文案；busy 时禁用全部控制按钮并显示「执行中…」 |
| `frontend/src/pages/Lists.tsx` | 加载失败显示错误 + 重试 |
| `frontend/src/pages/SettingsPage.tsx` | 加载/保存失败提示；Save busy 禁用 |

然后 `docker compose build frontend` 并重启 frontend 容器。未改交易架构或安全默认值。

---

## 1. 执行前预检

| 项 | 结果 |
| --- | --- |
| `http://127.0.0.1:8080` | HTTP 200 |
| Compose | frontend / backend / execution-worker 均 Up |
| backend `EXECUTION_MODE` | **mock** |
| worker `EXECUTION_ENABLED` | **false** |
| `/api/status` | **STOPPED**，`trading_enabled=false`，position **FLAT** |
| `/api/orders` | `[]` |

---

## 2. 按钮测试

### 2.1 启动

- UI 立即 **禁用全部按钮**，显示「执行中…」
- 页面结果：**成功 state=RUNNING**
- `/api/status`：`RUNNING`，`trading_enabled=true`，position **FLAT**，Last Order **—**
- `/api/orders`：`[]`
- worker：`POST /rpc/connect`、`POST /rpc/configure` 各一次；**无** `place_order` / `cancel` / `set_leverage`
- worker 之后 `execution_enabled=false`，`READY`，`sync=LIVE`（connect 后只读就绪，不是下单）

### 2.2 停止

- 执行中按钮禁用
- 页面结果：**成功 state=STOPPED**
- backend：**STOPPED**，`trading_enabled=false`，FLAT
- 无新订单

### 2.3 平仓并停止

- 当前 FLAT
- 页面结果：**成功（already_flat）**
- 状态仍 **STOPPED**，`trading_enabled=false`
- 无 `place_order`

### 2.4 紧急停止

- 当前 FLAT、无挂单
- 页面结果：**成功（already_flat）**
- 最终 **STOPPED**，`trading_enabled=false`，`estop=true`
- 无异常页面
- 无 `place_order` / `cancel_order`

backend 日志对应四次 POST，均为 200：

```
POST /api/trading/start
POST /api/trading/stop
POST /api/trading/close-and-stop
POST /api/trading/emergency-stop
```

---

## 3. 全部页面

| 页面 | 结果 |
| --- | --- |
| Dashboard | 控件结果与 STOPPED / FLAT / estop=true 一致 |
| Settings | SQLite 表单加载（BTC-USD / ema5break）；未点 Save |
| Strategy | ema5break JSON 加载 |
| Orders | `[]` |
| Trades | `[]` |
| Events | start / user_stop / close_already_flat 事件可见 |

加载失败时会显示红色错误和「重试」，不再永久 Loading。本轮各页均加载成功。

---

## 4. 浏览器错误与写接口

| 检查 | 结果 |
| --- | --- |
| `error` / `unhandledrejection` | **[]** |
| worker `place_order` | **无** |
| worker `cancel_order` | **无** |
| worker `set_leverage` | **无** |
| `/api/orders` 最终 | `[]` |

---

## 5. 最终 `/api/status`

```json
{"system_state":"STOPPED","trading_enabled":false,"estop":true,"position":{"symbol":"BTC-USD","side":"FLAT","size":"0"},"last_order":null,"worker_state":"READY","sync_status":"LIVE"}
```

（字段已缩写。）`estop=true` 来自紧急停止，符合该按钮语义。

---

## 6. 观察（不判 FAIL）

- 「启动」会 `POST /rpc/connect`，worker 从 NOT_READY 变为 READY/LIVE，但 **`execution_enabled` 仍为 false**，没有真实下单。
- 紧急停止在 already_flat 时系统事件 reason 是 `close_already_flat`（现有 backend），UI 已显示成功。

---

## 7. 结论

四个控件都接到对应 backend API，FLAT 时平仓/紧急停止不提交订单，最终 STOPPED。前端错误提示与防重复点击已补上。

**STEP_5_RESULT = PASS**
