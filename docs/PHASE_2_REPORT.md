# PHASE 2 报告：FINALIZATION

**状态：** PHASE 2 FINALIZATION 完成并停止。未进入 PHASE 3。未连接 Hyperliquid，未发送真实订单。  
**日期：** 2026-09-01  
**提交：** 见文末 Git

标记约定：

- **VERIFIED**：本会话实际执行且通过
- **NOT VERIFIED**：未跑通，或外部条件阻止
- **N/A**：本阶段明确不做

## PHASE 2 FINALIZATION 完成情况

| 项 | 结果 |
| --- | --- |
| SUBMITTING 崩溃恢复（不重下单、不误 REJECTED） | 代码 + 确定性单测 **VERIFIED** |
| Reservation 与订单对账一致 | 代码 + 单测 **VERIFIED** |
| UNKNOWN / RECOVERY 禁止新开仓 | 单测 **VERIFIED**（含恢复中 LONG/SHORT） |
| Backend ↔ Worker 真实 HTTP（Mock adapter） | pytest 拉起真实 worker 进程 **VERIFIED** |
| Docker CLI / Compose 配置 | **VERIFIED** |
| `docker compose build` / `up -d` / 卷数据保持 | **NOT VERIFIED** — Docker Hub 网络/认证连接失败 |
| 容器内 Python 3.12 pytest | **NOT VERIFIED**（无本地 `python:3.12` 镜像且无法拉取） |
| 本机 Python 3.14 pytest | **VERIFIED** |
| Frontend `npm run build` | **VERIFIED**（本机 Node，不是容器） |
| 浏览器 E2E | **NOT VERIFIED** |
| 真实 Hyperliquid / Hummingbot | **N/A** |

## 1. 本次修改

1. **SUBMITTING 崩溃恢复入口** `TradingController.reconcile_after_restart()`：查询-only，永不调用 `place_order`。启动时在 `seed_defaults` 中、在 Recovery bootstrap 之前执行；`start()` 在离开 RECOVERY / 进入 STARTING 之前也先对账。
2. **SUBMITTING → UNKNOWN**：重启发现 `SUBMITTING` 时写入 `crash while SUBMITTING; will not resubmit`，再走既有 `_reconcile_unknown`（`get_order` + `get_fills` + `get_position`）。
3. **Reservation**：确认不存在且无成交且仓位与未提交相容 → `REJECTED` 并按 `order_id` 释放；订单/成交存在 → 恢复真实状态并保持 reservation；查询失败 → 保持 UNKNOWN + RECOVERY + reservation。
4. **HttpExecutionClient**：内部 RPC 使用 `trust_env=False`，避免系统 HTTP 代理把 `127.0.0.1` / worker URL 拐走。
5. **Mock worker**：`query_fail` 仅让 `get_order` / `get_fills` 失败（504），不破坏 Guard 所需的 `get_position`；测试钩子 `POST /rpc/test/query_fail`。
6. **测试**：`tests/test_submitting_recovery.py`（场景 A–D + reservation）；`tests/test_http_worker.py`（真实 uvicorn worker + `HttpExecutionClient`）。

未改架构。未接入 Hummingbot / Hyperliquid。未改 Dockerfile / 镜像源 / Python 版本。

## 2. SUBMITTING 恢复机制

订单状态机不变：

`PENDING_SUBMISSION` → `SUBMITTING` → `place_order()` → ACK / OPEN / PARTIAL / FILLED / REJECTED / CANCELED

`UNKNOWN` = 已经尝试执行，最终结果无法确认。

崩溃时若行仍为 `SUBMITTING`（`place_order` 可能已发出、进程在返回前退出）：

- **禁止** `SUBMITTING` → 再次 `place_order()`
- **禁止** `SUBMITTING` → 直接 `REJECTED` → 新建订单
- **必须** `SUBMITTING` → UNKNOWN，然后查询对账

只有三路都成功且证明原请求未执行（无 order、无该 cloid 的 fill、仓位与未成交相容）才结束为 `REJECTED`。否则保持 UNKNOWN / RECOVERY。

自动化测试（文件 SQLite，第二进程 `bootstrap_schema=False`，无 sleep 模拟崩溃）：

| 场景 | 结果 |
| --- | --- |
| A 重启后交易所已有 FILLED | 恢复 FILLED；`place_calls == 0`；新 LONG 拒绝 |
| B 无 order / 无 fill / FLAT | REJECTED；释放 reservation；允许一次新 LONG（`place_calls == 1`，不是恢复重发） |
| C 查询失败 | UNKNOWN + RECOVERY；`place_calls == 0` |
| D 恢复中 LONG/SHORT | 拒绝；`place_calls == 0` |

## 3. Reservation 恢复机制

开仓路径：`open_reservations` CAS 占用 → 落订单 → `place_order`。崩溃时 reservation 与 SUBMITTING 订单一起留在 SQLite。

- A：订单已成交 → reservation **保持**，第二 LONG 不能因为重启而通过
- B：证明未执行 → **释放** reservation，系统不永久卡死，随后独立 LONG 可以开仓
- C：无法确认 → **保持** reservation + RECOVERY，禁止开仓

恢复逻辑与 `_reconcile_unknown` 共用，不单独“重启清锁”。

## 4. UNKNOWN 机制

查询任一路失败 → UNKNOWN + `enter_recovery("unconfirmed_place")`。  
有 fill 无 order、或开仓仓位非 FLAT 而无 matching order → 不得视为未提交。  
UNKNOWN / RECOVERY 期间 Guard 禁止新开仓。永不自动再 `place_order`。

## 5. cloid 幂等

未改 schema。`orders.cloid` / `intent_id` / `request_id` UNIQUE 仍在。Worker Mock 对重复 cloid 返回已有订单、不新开仓。恢复路径不生成新 cloid。

## 6. Controller 边界（代码审查）

生产路径中唯一调用 `ExecutionClient.place_order` 的是 `TradingController._submit`。

| 路径 | 结论 |
| --- | --- |
| Strategy → `place_order` | 无 |
| API → Worker 直接下单 | 无；`/api/trading/*` 进 Controller |
| Frontend → Worker | 无 |
| Recovery / `reconcile_after_restart` → `place_order` | 无（只查询） |
| Worker 自动补单 / 自动反手 | 无 |
| UNKNOWN → 自动重新 `place_order` | 无 |

未来 Hyperliquid 状态仍经 ExecutionAdapter；SQLite 仍是配置、镜像、审计，不是仓位真相源。

## 7. Backend ↔ Worker 真实 HTTP

**VERIFIED**（本机 Python 3.14，pytest 子进程）。

架构：Backend TestClient → `HttpExecutionClient`（真实 HTTP）→ uvicorn `execution-worker` 进程 → `MockExecutionAdapter`。

**不是** `FakeExecutionClient`。未连 Hyperliquid。

已实际跑通：

1. Backend 启动  
2. Execution Worker 进程启动  
3. Backend 经 HTTP 连 Worker（`/api/health` `worker_ok`）  
4. FLAT + LONG  
5. Worker Mock 开仓，HTTP `GET /rpc/position` 为 LONG  
6. Backend 收到执行结果，本地 mirror LONG  
7. LONG + LONG 拒绝  
8. 有仓 + SHORT 拒绝（反手）  
9. CLOSE  
10. CLOSE 后 FLAT  
11. `network_before_accept` + `query_fail` → UNKNOWN + RECOVERY  
12. Worker HTTP 504 / 进程停止后 `worker_ok` false  
13. 同端口重启 Worker 后 LONG 仍拒绝，`place_calls` 不增加  

健康检查对 bind 的短轮询只用于等端口就绪，不用于模拟崩溃。

## 8. Docker 验证

Docker Desktop **已安装且 engine 在运行**。CLI：

`C:\Users\Admin\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`

本会话实际命令：

| 命令 | 结果 |
| --- | --- |
| `docker --version` | **VERIFIED** Docker version 29.7.2 |
| `docker compose version` | **VERIFIED** v5.4.0 |
| `docker info` | **VERIFIED**（Server 29.7.2；**Images: 0**） |
| `docker compose config` | **VERIFIED**（exit 0） |
| `docker compose build` | **NOT VERIFIED** — `auth.docker.io/token`：`dial tcp 31.13.75.12:443` 连接失败（`python:3.12-slim-bookworm` / `node:22-alpine` 均无法拉取） |
| `docker compose up -d` | **NOT VERIFIED**（无镜像） |
| `compose ps` / 三服务日志 / 容器内 `GET /api/health` | **NOT VERIFIED** |
| `down` 后再 `up` 的 settings / 策略参数 / SQLite / logs | **NOT VERIFIED** |

未修改 Dockerfile 或改用国内镜像。未把 “Docker Desktop 已安装” 写成 Compose 运行成功。本机没有可复用的 `python:3.12` 镜像。

原因归类：**external Docker Hub network/auth connectivity**，不是本仓库 Compose/代码缺陷。

## 9. Python 3.12 验证

**NOT VERIFIED。** 不能用本机 3.14 测试代替。

## 10. Frontend build

```
frontend> npm run build   # tsc --noEmit && vite build
→ dist/ 产出成功
```

**VERIFIED**（本机）。容器内 frontend **NOT VERIFIED**。浏览器点选控制按钮 **NOT VERIFIED**。

## 11. 全部测试结果

### 本机 Python 3.14.5

```
backend> python -m pytest tests -q
→ 38 passed

execution-worker> python -m pytest tests -q
→ 4 passed
```

**VERIFIED**（3.14）。覆盖包括此前安全矩阵，以及本次：

- SUBMITTING 崩溃 A/B/C/D 与 reservation
- 真实 HTTP worker 集成
- FLAT+LONG 成功；LONG+LONG / LONG+SHORT / SHORT+LONG / SHORT+SHORT 拒绝
- 有仓禁止新开仓；UNKNOWN / RECOVERY 禁止新开仓
- CLOSE 平仓且不自动反手
- 并发双 LONG 仅一次 `place_order`（既有测试）
- 重复 cloid 数据库拒绝（既有测试）

### Docker Python 3.12

**NOT VERIFIED。**

## 12. VERIFIED

- SUBMITTING 崩溃恢复与 reservation 对账（单测）
- Backend ↔ Mock Worker 真实 HTTP 集成（pytest + uvicorn 子进程）
- 本机 Python 3.14 全量 pytest（backend 38 + worker 4）
- 本机 frontend `npm run build`
- Docker CLI / Compose version / `docker info` / `compose config`
- TradingController 仍是唯一下单入口（代码审查）

## 13. NOT VERIFIED

- `docker compose build` / `up -d` / 三容器运行
- Docker Volume/bind mount 数据保持（settings / 策略参数 / SQLite / logs）
- 容器内 Python 3.12 与容器内 pytest
- 浏览器 E2E
- 容器内 `GET /api/health` 与 `GET /api/status`

## 14. N/A

Hummingbot、Hyperliquid 主网/testnet、真实密钥、策略沙箱、K 线、回测、多币种/多策略/多账户、Redis/Kafka/PostgreSQL/K8s。

## 15. Docker Hub

`docker compose build` 失败于：

`Post https://auth.docker.io/token` → `dial tcp 31.13.75.12:443` 对端无响应。

这是**环境限制**（Docker Hub 网络/认证连通性），不是 PHASE 2 代码未完成。`docker info` 显示本地 **Images: 0**，无法用已有镜像绕过拉取。

## 16. 当前已知限制

- 本机 Docker Hub 不可用时无法验证 Compose 运行与 Python 3.12 容器。
- Windows 用户级 Docker CLI 可能不在默认 PATH。
- 本机若配置了 HTTP 代理，未设 `trust_env=False` 时 httpx 可能把 loopback worker 流量送进代理；已在 `HttpExecutionClient` 关闭。
- 生产必须先 `alembic upgrade head`；裸 uvicorn 不建表。
- 完整 Hummingbot 执行层属于后续 Phase。

## 17. Git commit

工作树排除 `.env` 实值、密钥、SQLite 生产库、`node_modules`、pytest 缓存。

提交说明：`PHASE 2 FINALIZATION: SUBMITTING recovery and live HTTP worker tests`

**停止。不进入 PHASE 3。**
