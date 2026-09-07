# STEP 7 — SECURE STRATEGY UPLOAD BACKEND

**日期：** 2026-09-04  
**环境：** mock backend + Compose worker `EXECUTION_ENABLED=false`。未连接 Hyperliquid 主网交易。未发送订单。未启动策略循环。未读取或保存真实密钥。未改 Compose / Dockerfile / `.env` 默认值。未改 TradingController 交易规则。未 git commit。  
**本文件不含** API secret / 私钥。

**STEP_7_RESULT = PASS**

---

## 1. 做了什么

实现自定义策略的安全上传、AST/YAML 校验、版本存储和显式激活。上传成功**不会**自动启用或启动策略。激活只在已注册版本上切换 `active_strategy`，系统保持 `STOPPED`。

| Method | Path | 行为 |
| --- | --- | --- |
| POST | `/api/strategy/upload` | multipart，仅 `strategy.py` + `manifest.yaml` |
| POST | `/api/strategy/activate` | JSON `{"file_hash": "<64 hex>"}`，仅已注册版本 |

校验失败：HTTP 400 + `{"ok":false,"reason":"..."}`。不留 `.tmp-*`。不改当前 `active_strategy`。不对上传文件 `exec` / `import`。

激活拒绝：未注册、RUNNING、RECOVERY 及其他非 STOPPED、有仓、UNKNOWN 仓位、unresolved / UNKNOWN order、仓位查询失败。成功后 `trading_enabled=false`，写 audit `strategy_activate` 与 event `strategy_status`。

存储：`SHA-256(strategy.py + "\\n---\\n" + manifest.yaml)` → `strategies/versions/<sha256>/`。临时目录写入后 `replace` 原子移动。已有 hash 不覆盖、不插入第二行（`duplicate: true`）。不写入 `strategies/ema5break/` 等可执行入口。

manifest 用 stdlib 受限 YAML 子集解析（拒绝 `!!` / `&` / `*`），不执行策略代码。必填：`name`、`version`、交易对（`symbol` 或 `trading_pair`）、周期（`interval` / `period` / `timeframe`）。

---

## 2. API 示例

合法上传：

```http
POST /api/strategy/upload
Content-Type: multipart/form-data

strategy.py, manifest.yaml
```

Compose 实测成功响应：

```json
{
  "ok": true,
  "duplicate": false,
  "file_hash": "c0ee5c5cc3045e02d6c9d4ee526b57612a696a1d89fbf36b3acb45bb1306bf56",
  "name": "custom_hold",
  "version": "1.0.0",
  "path": "/app/strategies/versions/c0ee5c5cc3045e02d6c9d4ee526b57612a696a1d89fbf36b3acb45bb1306bf56",
  "activated": false
}
```

显式激活：

```http
POST /api/strategy/activate
{"file_hash":"c0ee5c5cc3045e02d6c9d4ee526b57612a696a1d89fbf36b3acb45bb1306bf56"}
```

```json
{
  "ok": true,
  "name": "custom_hold",
  "version": "1.0.0",
  "file_hash": "c0ee5c5cc3045e02d6c9d4ee526b57612a696a1d89fbf36b3acb45bb1306bf56",
  "state": "STOPPED",
  "trading_enabled": false
}
```

---

## 3. 拒绝危险文件的证据

Compose `127.0.0.1:8000` 实测：

| 输入 | HTTP | reason |
| --- | --- | --- |
| `import subprocess` | 400 | `dangerous import is not allowed: subprocess` |
| `place_order("BTC-USD")` | 400 | `direct trading call is not allowed: place_order` |
| filename `../../etc/passwd` | 400 | `path traversal is not allowed` |

backend 测试另覆盖：缺失/非法 manifest、超大文件（`strategy.py` > 256KiB）、额外文件、绝对路径、`os` / http 类导入、重复 hash、RUNNING / 有仓 / UNKNOWN order / RECOVERY 拒绝激活、激活后仍 STOPPED、上传与激活 `place_calls=cancel_calls=set_leverage_calls=0`。模块级 `open(...).write(...)` 上传成功但标记文件不存在（证明未执行上传代码）。

---

## 4. 测试结果

### backend（`python -m pytest -q`，工作目录 `backend`）

**77 passed**（含 `tests/test_strategy_upload.py`）

| 用例 | 结果 |
| --- | --- |
| 合法策略上传成功 | pass |
| manifest 缺失或非法拒绝 | pass |
| 危险 import 拒绝 | pass |
| 直接下单调用拒绝 | pass |
| 路径穿越 / 额外文件 / 绝对路径拒绝 | pass |
| 超大文件拒绝 | pass |
| 重复 hash 不产生重复版本 | pass |
| RUNNING 不能激活 | pass |
| 有仓位不能激活 | pass |
| RECOVERY 不能激活 | pass |
| UNKNOWN order 不能激活 | pass |
| 激活后仍为 STOPPED | pass |
| 上传/激活不调用 place/cancel/set_leverage | pass |

### execution-worker

**78 passed, 13 skipped**

worker 代码未改；全量回归通过。

### frontend `npm run build`

`tsc --noEmit && vite build` **成功**。本 STEP 未改前端源码。

---

## 5. mock Compose 本地验证

仅重建并 recreate **backend** 镜像/容器。未改 compose 文件、Dockerfile、`.env`。未点「启动」。未调用 `place_order` / `cancel` / `set_leverage`。

| 项 | 结果 |
| --- | --- |
| backend `EXECUTION_MODE` | **mock** |
| worker `EXECUTION_ENABLED` | **false** |
| 验证前 | STOPPED，FLAT，`active_strategy=ema5break`，`trading_enabled=false` |
| 合法上传 | **200**，`activated=false`，写入 `strategies/versions/<sha256>/` |
| 危险 import / 直接下单 / 路径穿越 | **400**，见第 3 节 |
| 激活 | **ok=true**，STOPPED，`trading_enabled=false`，active=`custom_hold` `1.0.0` |
| `strategies/ema5break/strategy.py` SHA-256 | **未变** |
| worker 日志 `place_order` / `cancel_order` / `set_leverage` | **无匹配** |

---

## 6. 改动文件

- `backend/app/strategy/` — `yaml_lite.py`、`validate.py`、`store.py`、`service.py`
- `backend/app/api/routes.py` — upload / activate
- `backend/app/schemas/__init__.py` — `StrategyActivateIn`
- `backend/app/core/config.py` — `strategies_dir` 默认 `strategies/versions`
- `backend/app/deps.py`、`backend/app/main.py` — `StrategyService`
- `backend/app/repositories/__init__.py` — `get_by_hash` / `count_by_hash`
- `backend/tests/conftest.py` — 测试写入临时 versions 目录
- `backend/tests/test_strategy_upload.py`
- `.gitignore` — `/strategies/versions/`

未改：TradingController 交易规则、Compose、Dockerfile、`.env` 默认值、execution-worker、策略运行循环。

---

## 7. 未做（下一步）

未实现策略运行循环、独立策略进程、IPC、或自动评测 uploaded `evaluate()`。激活只切换已注册版本并保持停止。
