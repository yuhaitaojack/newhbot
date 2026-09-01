# PHASE 2 报告：基础项目架构（含修正）

**状态：** PHASE 2 修正完成并停止。未进入 PHASE 3。未连接 Hyperliquid，未发送真实订单。  
**日期：** 2026-09-01  
**提交：** 见文末 Git

标记约定：

- **VERIFIED**：本会话实际执行且通过
- **NOT VERIFIED**：未跑通，或外部条件阻止
- **N/A**：本阶段明确不做

## PHASE 2 修正完成情况

| 项 | 结果 |
| --- | --- |
| UNKNOWN 状态机语义 | 已改代码 + 单测 **VERIFIED** |
| 生产路径去掉 `create_all` | 已改代码；Alembic 单测 **VERIFIED**；容器内 upgrade **NOT VERIFIED** |
| 并发开仓 reservation | SQLite CAS + 部分唯一索引；并发单测 **VERIFIED** |
| cloid / intent / request UNIQUE | schema + IntegrityError 单测 **VERIFIED** |
| CLOSE / 控制按钮行为 | 单测 **VERIFIED**（非浏览器） |
| UNKNOWN 恢复四类场景 | 单测 **VERIFIED** |
| Docker Desktop 存在性 | `docker --version` / `compose version` / `compose config` **VERIFIED** |
| `compose build` / `up -d` / 数据保持 | **NOT VERIFIED**（拉镜像失败） |
| Python 3.12 容器内 pytest | **NOT VERIFIED**（无本地 `python:3.12` 镜像且无法从 Docker Hub 拉取） |
| Frontend `npm install` / `npm run build` | **VERIFIED** |
| 浏览器 E2E | **NOT VERIFIED** |

## 本次修改

### 1. 订单状态机

不再把“准备发送”标成 UNKNOWN。

| 状态 | 含义 |
| --- | --- |
| PENDING_SUBMISSION | 意图已落库，尚未调用 `place_order` |
| SUBMITTING | 正在调用 `place_order` |
| ACK / OPEN / PARTIAL / FILLED / REJECTED / CANCELED | 已确认结果 |
| UNKNOWN | **已经尝试执行**，最终结果无法确认 |

UNKNOWN 解除为 REJECTED（视为未提交成功）仅当同时确认：

1. `get_order(cloid)` 不存在  
2. `get_fills()` 无该 cloid  
3. `get_position()` 与“未成交”相容（开仓则须 FLAT）

仅“没有 open order”不够。查询失败则保持 UNKNOWN + RECOVERY，且 **永不自动再次 `place_order`**。

### 2. 数据库初始化

生产 lifespan **不再** `Base.metadata.create_all()`。  
Docker CMD 仍为 `alembic upgrade head && uvicorn`。  
测试：`create_app(..., bootstrap_schema=True)` → `create_all_for_tests()`。  
重启测试：第二进程 `bootstrap_schema=False`，依赖已有 SQLite 文件。

新增 Alembic `0002_order_constraints`。

### 3. 并发开仓锁

不用进程内 bool。使用：

- 单行表 `open_reservations`：`UPDATE ... SET order_id=? WHERE id=1 AND order_id IS NULL`（SQLite 写锁 + rowcount CAS）
- 部分唯一索引：同一 `symbol` 最多一条非 reduce-only 的 inflight 开仓单

原因：API 请求可并发；SQLite 事务/约束在进程崩溃后仍在，bool 不在。

### 4. cloid 幂等

`orders.cloid` UNIQUE（0001 已有）。0002 增加 `intent_id`、`request_id` UNIQUE。关系：一个 intent → 一个 cloid → 一行 order。重复插入 **VERIFIED** 触发 `IntegrityError`。

### 5. CLOSE / 控制面

CLOSE 只平仓，不在同一 `handle_signal` 里开反向仓。有仓时 SHORT/LONG 仍拒绝反手。CLOSE 完成且 FLAT 之后的独立 SHORT 是新开仓，不是自动反手。

`close-and-stop` / `close-and-continue` / `emergency-stop` 单测检查 `system_state`、`trading_enabled`、仓位，不只 HTTP 200。

## 测试结果

### Python 3.14 local

本机 `C:\Python314`：

```
backend> python -m pytest tests -q
→ 34 passed

execution-worker> python -m pytest tests -q
→ 4 passed
```

**VERIFIED**（3.14，不能等同 3.12）。

覆盖包括：Alembic 含 `open_reservations` 与唯一索引；settings 跨进程恢复且第二次启动无 `create_all`；FLAT+LONG / 有仓拒绝 / 反手拒绝；并发双 LONG 仅一次 `place_order`；UNKNOWN 查询失败保持 / 三路确认后 REJECTED；timeout 后 `get_order` 恢复 OPEN；fill 无 order 保持 UNKNOWN；LONG/SHORT+CLOSE→FLAT；控制按钮状态。

### Python 3.12 Docker

**NOT VERIFIED**。本机无 `python:3.12` 镜像。`docker compose build` 拉取 `python:3.12-slim-bookworm` 时 Docker Hub OAuth 失败（见下）。

## Docker 验证结果

Docker Desktop **已安装且进程在运行**。CLI 不在默认 PATH，实际二进制：

`C:\Users\Admin\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`

| 命令 | 结果 |
| --- | --- |
| `docker --version` | **VERIFIED** Docker version 29.7.2 |
| `docker compose version` | **VERIFIED** v5.4.0 |
| `docker compose config` | **VERIFIED**（pytest 同样通过） |
| `docker compose build` | **NOT VERIFIED** — `auth.docker.io/token` 连接被拒绝（`dial tcp 31.13.69.245:443: connectex: ... actively refused`） |
| `docker compose up -d` | **NOT VERIFIED**（无镜像） |
| `down` 后再 `up` 的 SQLite/settings/参数/logs 保持 | **NOT VERIFIED** |

未把“Compose 文件存在”或“Docker Desktop 在跑”写成 `up -d` 通过。

## Frontend build 结果

```
frontend> npm install
frontend> npm run build   # tsc --noEmit && vite build
```

**VERIFIED**（`dist/` 产出成功）。浏览器点选五个按钮 **NOT VERIFIED**。

## 代码审查（修正后）

1. TradingController 仍是唯一 `place_order` 调用方。  
2. Strategy 仍只返回信号。  
3. API `/api/trading/*` 仍只进 Controller。  
4. Worker 仍不根据策略补单。  
5. Worker 仍无自动反手。  
6. UNKNOWN / SUBMITTING 仍禁止新开仓。  
7. RECOVERY 仍禁止新开仓。  
8. 交易所状态仍经 ExecutionAdapter；未来 Hyperliquid 可替换 Mock。  
9. SQLite 仍是配置/审计/镜像，不是仓位真相。  
10. Backend 仍不 import Hummingbot 对象；v2.16.0 connector 仍只能进 worker。当前陷阱：Hub 镜像拉不下来，还不构成架构否决。

## 仍然 NOT VERIFIED

- 浏览器 E2E  
- `docker compose build` / `up -d` / 卷数据保持  
- 容器内 Python 3.12 pytest  
- backend ↔ execution-worker 真实 HTTP（单测用 Fake）  
- 真实 Hyperliquid / Hummingbot：**N/A**（本阶段禁止）

## 已知限制

- Docker Hub 在本机当前网络下无法授权拉取公共镜像。  
- Windows 用户级 Docker CLI 需自行加入 PATH。  
- 完整 Recovery 矩阵、策略沙箱、真实执行层属于后续 Phase。  
- 生产必须先 `alembic upgrade head`；裸 `uvicorn` 不会建表。

## Git commit

工作树提交前已排除 `.env` 实值、密钥、SQLite 生产库、`node_modules`。

提交说明：`PHASE 2: order state, reservation lock, and verification fixes`

**停止。不进入 PHASE 3。**
