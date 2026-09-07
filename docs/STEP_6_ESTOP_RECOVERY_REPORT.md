# STEP 6 — EMERGENCY STOP RECOVERY UX

**日期：** 2026-09-04  
**环境：** mock backend + Compose worker `EXECUTION_ENABLED=false`。未设真实密钥。未点「启动」。未实现策略循环或主网交易。  
**本文件不含** API secret / 私钥。

**STEP_6_RESULT = PASS**

---

## 1. API 行为

`POST /api/trading/clear-estop` 走 `TradingController.clear_estop`。只读查询执行层仓位/挂单/多标的仓位。不调用 `place_order` / `cancel` / `set_leverage`。不把 `trading_enabled` 设为 true。不进入 RUNNING。

成功（全部检查通过）：

```json
{"ok":true,"estop":false,"state":"STOPPED","reason":"estop_cleared_still_stopped"}
```

检查失败：`ok=false`，`estop` 保持 true，状态保持 STOPPED 或进入 RECOVERY，写审计 `clear_estop_rejected`，返回可读 `reason`。

`PUT /api/settings` 不再接受 `estop` 字段。Compose 实测：`{"estop":false}` 之后 `estop` 仍为 true。

---

## 2. 测试结果

### backend（`python -m pytest -q`，工作目录 `backend`）

**62 passed**（含 `tests/test_clear_estop.py`）

覆盖：

| 用例 | 结果 |
| --- | --- |
| FLAT + 无挂单可解除 | pass |
| 有仓位拒绝 | pass |
| 有挂单拒绝 | pass |
| 有 UNKNOWN order 拒绝 | pass |
| 有 foreign position 拒绝 | pass |
| 不启动策略 / 不进入 RUNNING | pass |
| 不调用 place / cancel / set_leverage | pass |
| settings 不能绕过 | pass |
| estop 未锁定时拒绝 | pass |

### execution-worker

**78 passed, 13 skipped**

worker 代码未改；全量回归通过。

### frontend `npm run build`

`tsc --noEmit && vite build` **成功**。

---

## 3. 前端

Dashboard 仅在 `estop=true` 显示「解除紧急停止」。点击后 `window.confirm`。请求期间禁用全部控制按钮并显示「执行中…」。成功文案：**已解除紧急停止，但系统仍保持停止**。失败显示红色可读原因。不自动点启动。

Compose UI 实测：确认框被调用；成功后 `estop=false`、STOPPED、`trading_enabled=false`，按钮消失。

---

## 4. mock Compose 本地验证

| 项 | 结果 |
| --- | --- |
| worker `EXECUTION_ENABLED` | **false** |
| 解除前 | STOPPED，estop=true，FLAT |
| PUT settings `estop:false` | estop **仍 true** |
| POST `/api/trading/clear-estop` | **ok=true**，STOPPED |
| UI 再 latch（emergency-stop already_flat）后点解除 | 确认 + 成功文案 |
| worker `place_order` / `cancel` / `set_leverage` | **无** |

---

## 5. 改动文件

- `backend/app/controllers/trading_controller.py` — `clear_estop`
- `backend/app/api/routes.py` — 路由；settings 忽略 estop
- `backend/app/schemas/__init__.py` — 去掉 SettingsUpdate.estop
- `backend/tests/test_clear_estop.py` — 新测试
- `backend/tests/fakes.py` — cancel / set_leverage 计数
- `frontend/src/pages/DashboardPage.tsx` — 按钮、确认、busy、成功文案
- `docs/API_DESIGN.md` — 登记路径

---

## 6. 结论

受保护的 clear-estop 流程已落地：检查失败保持锁存，settings 不能绕过，前端需确认且保持停止。未做下一阶段策略循环或实盘。

**STEP_6_RESULT = PASS**
