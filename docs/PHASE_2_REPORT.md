# PHASE 2 报告：基础项目架构、Docker、数据库与进程边界

**状态：** 代码与单测已落地并停止。未连接 Hyperliquid，未发送真实订单，未进入 PHASE 3。  
**日期：** 2026-09-01  
**执行层：** MockExecutionAdapter only  
**Hummingbot：** 未接入（版本锚点仍为 PHASE 1 的 v2.16.0）

任何没有实际跑过的检查一律标记 **NOT VERIFIED**。下文不把「代码存在」写成「功能验证通过」。

## 1. 实际完成内容

已实现：

- 三进程骨架：`frontend` → `backend`（Trading Service）→ `execution-worker`（Mock）
- SQLite + Alembic `0001_initial` + WAL pragma
- 设置与策略参数持久化（SQLite，不是 localStorage / `.env`）
- TradingController 作为唯一交易入口（LONG/SHORT/CLOSE/HOLD）
- PositionGuard：双 FLAT、无 UNKNOWN、非 RECOVERY、RUNNING、币种匹配
- UNKNOWN：先写库再 RPC；异常只 `get_order(cloid)`，禁止立即重下
- REST `/api/*` 与 WebSocket `/ws`
- 最小 React UI（Dashboard / Settings / Strategy / Orders / Trades / Events + 五个控制按钮）
- Docker Compose 文件与三份 Dockerfile
- 结构化 JSON 日志（交易字段 + 密钥关键词过滤）
- 示例策略 `strategies/example_strategy`（只返回 HOLD）

未实现（有意留给后续 Phase）：

- 真实 Hyperliquid / Hummingbot connector
- 完整策略 Runtime / 插件沙箱容器
- 完整 Recovery 场景矩阵
- 认证、远程访问、K 线、回测、AI

## 2. 项目目录

```
newhbot/
  AGENTS.md
  docker-compose.yml
  .env.example
  backend/                 # FastAPI 控制面
    app/{api,core,models,schemas,services?,controllers,execution,strategy,recovery,events,repositories}
    migrations/            # Alembic（目录名避免与 alembic 包冲突）
    tests/
  execution-worker/        # Mock 执行进程
    app/{main,mock_adapter,protocol}
    tests/
  frontend/                # Vite + React + Tailwind
    src/{pages,components,api.ts}
  strategies/example_strategy/
  data/                    # bind mount：SQLite
  logs/                    # bind mount：日志
  docker/README.md
  docs/
```

`backend/app/services/` 未单独铺一层；业务编排在 Controller + repositories。Strategy Runtime 仍在 backend 进程内，Compose 未拆策略容器；`docker-compose.yml` 注释预留了 sandbox 接口。

## 3. 技术栈

| 层 | 选用 |
| --- | --- |
| Backend | Python 3.11+（镜像 3.12-slim；本机单测跑在系统 Python 3.14）FastAPI, Pydantic, SQLAlchemy 2, Alembic, asyncio, httpx |
| Worker | FastAPI + Mock adapter |
| Frontend | React 18, TypeScript, Vite, Tailwind, 少量 shadcn 风格 Button/Card |
| DB | SQLite WAL |
| Deploy | Docker Compose，相对路径 volume `./data` `./logs` `./strategies` |

未引入 Redis / Kafka / PostgreSQL / Kubernetes。

## 4. 数据库设计

见 `docs/DATABASE_DESIGN.md`。

表：`settings`, `strategy_versions`, `strategy_parameters`, `signals`, `orders`, `fills`, `trades`, `positions`, `account_snapshots`, `system_events`, `audit_logs`。

**Exchange State > Local DB。** `positions` 只是镜像/审计。Alembic 升级单测已通过（见第 13 节）。Docker 内 `alembic upgrade head` **NOT VERIFIED**（Docker 未安装）。

## 5. 服务边界

见 `docs/SERVICE_BOUNDARIES.md`。

- API / Frontend / Strategy **不得**直接打 Execution Worker
- Controller 是唯一 `place_order` 调用方
- Worker 不保存业务策略、不写控制面 SQLite
- 策略只输出信号

## 6. API

见 `docs/API_DESIGN.md`。

已实现 PHASE 2 清单中的 health/status/settings/strategy/positions/orders/fills/trades 与五个交易控制端点。另有开发用 `POST /api/trading/signal`（生产 Runtime 应走内部 Controller）。

REST 行为由 pytest + Starlette TestClient **已验证**（见第 13 节）。浏览器里点按钮 **NOT VERIFIED**。

## 7. WebSocket

`/ws` 先发 `hello`，再推 EventHub 增量：`system_status`, `strategy_status`, `position`, `order`, `fill`, `trade`, `signal`。客户端约定：断线后 `GET /api/status` + 列表 snapshot，再接 WS。

单测只验证了 `websocket_connect` 收到 `hello`。断线重连全路径、多客户端压测 **NOT VERIFIED**。

## 8. Mock Execution

`execution-worker`：`ExecutionAdapter` + `MockExecutionAdapter`。

模拟 FLAT/LONG/SHORT；下单行为 `fill` / `partial` / `reject` / `open` / `timeout_after_accept` / `network_before_accept`。RPC：`place_order`, `cancel_order`, `get_order`, `get_position(s)`, `get_balance`, `set_leverage`, `stream_events`。Adapter 另有 `open_long` / `open_short` / `close_position`（内部转 `place_order`）。测试钩子 `POST /rpc/test/behavior`。

Worker 单测 **4 passed**。HTTP 客户端对真实 worker 进程的集成 **NOT VERIFIED**（测试使用 in-process FakeExecutionClient）。

## 9. Controller

`TradingController`：start/stop/close-and-stop/close-and-continue/emergency-stop + `handle_signal`。

开仓路径：Guard → 持久化 intent/`cloid` → worker。禁止自动反手。API 不直接调用 worker。

Controller + Fake worker 路径 **已验证**。对接真实 execution-worker HTTP **NOT VERIFIED**。

## 10. Position Guard

`can_open_position()` 同时要求：

本地 FLAT AND 交易所 FLAT AND 无 UNKNOWN 订单 AND 非 RECOVERY AND 系统 RUNNING AND 目标币种正确 AND 交易所已连接 AND 无外盘异币种仓。

纯函数单测 + 经 Controller 的开仓拒绝路径 **已验证**。真实交易所快照 **N/A（本阶段 Mock）**。

## 11. UNKNOWN 机制

1. 插入订单 `PENDING_SUBMISSION` 并 commit  
2. 状态改为 `UNKNOWN` 再 commit  
3. 调用 `place_order`  
4. 异常：只 `get_order(cloid)`，**绝不重新提交**  
5. 查不到且无法证明未成交 → 保持 UNKNOWN 并进入 RECOVERY  

`network_before_accept`：UNKNOWN + 禁止再开仓 + `place_calls == 1` **已验证**。  
`timeout_after_accept`：同一 cloid 仅一条订单行 **已验证**。  
真实网络分区 / Hyperliquid `orderStatus` **NOT VERIFIED**。

## 12. Docker 状态

**BLOCKED: Docker未安装**

本机执行 `docker compose config`：PowerShell `CommandNotFoundException`（无法识别 `docker`）。与 PHASE 0 结论一致。未安装 Docker Desktop，未修改 Windows 环境。

因此下列全部 **NOT VERIFIED**：

- `docker compose up -d`
- `docker compose down` 后再 `up` 的数据保持
- 镜像构建
- 容器内 Alembic
- 端口 `127.0.0.1:8000` / `8080`
- Compose 文件语义（`docker compose config` 未能运行）

Compose 文件已按 Windows 相对路径编写：`./data` `./logs` `./strategies`。策略 Runtime 不是独立容器。

pytest `test_docker_compose_config`：**skipped**（`BLOCKED: Docker未安装`）。

## 13. 测试结果

命令（已实际运行）：

```
backend> python -m pytest tests -q
→ 20 passed, 1 skipped, 1 warning

execution-worker> python -m pytest tests -q
→ 4 passed
```

跳过：`test_docker_compose_config`（Docker 不存在）。

已覆盖：

| 项 | 结果 |
| --- | --- |
| Alembic 建表 | passed |
| Settings 同进程读写 | passed |
| Settings 重启后从 SQLite 恢复 | passed |
| 策略参数 `enabled=false` → default | passed |
| FLAT + LONG → 成功 | passed |
| LONG + LONG → 拒绝 | passed |
| LONG + SHORT → 拒绝（反手） | passed |
| SHORT + LONG → 拒绝 | passed |
| SHORT + SHORT → 拒绝 | passed |
| UNKNOWN → 禁止新开仓 | passed |
| RECOVERY → 禁止新开仓 | passed |
| REST 列表 + `/ws` hello | passed |
| 五个控制按钮 HTTP | passed |
| Mock fill / 网络异常模式 | passed（worker） |

未跑 / **NOT VERIFIED**：

- 前端 `npm install` / `npm run build`
- 浏览器端到端点击
- backend ↔ execution-worker 真实 HTTP
- Docker 全流程
- Windows Docker Desktop 数据卷保持

警告：Starlette TestClient 提示 `httpx` 将来改为 `httpx2`，测试仍通过。

## 14. Git 状态

提交信息：`PHASE 2: foundation architecture`（本报告随该提交写入）。

提交前检查：工作区无 `.env` 实值、无私钥/API key/钱包文件、无 SQLite 生产库纳入版本控制（`*.db` / `/data/*` / `backend/data/` 已 gitignore）。`.env.example` 仅基础设施占位。

## 15. 已知问题

1. **Docker Desktop 未安装** → Compose 无法验证。  
2. 本机 pytest 使用 **Python 3.14**；生产镜像规划 **3.12**。Hummingbot 仍不应跑在 3.14 上（PHASE 1 结论未变）。  
3. 应用 lifespan 使用 `create_all`，与 Alembic 并行。Docker 入口计划 `alembic upgrade head`，但 **NOT VERIFIED**。  
4. Strategy 参数写接口未做（PHASE 2 只要求结构 + 读 API）。  
5. Recovery 只是骨架（UNKNOWN 进入 RECOVERY）；完整对账矩阵未做。  
6. Frontend 未在浏览器验证；Settings 页把数值当文本框，够用但粗糙。  
7. Worker `stream_events` 目前是一次性 hello SSE，不是持续行情流。UI 走 backend EventHub。  
8. `POST /api/trading/signal` 是开发入口，不是生产策略热路径。

## 16. 下一阶段建议

PHASE 3 建议（需用户明确下令后再做）：

1. 安装 Docker Desktop 后验证 `compose config` / `up -d` / `down` / 数据保持。  
2. 把 Fake 换成对 `execution-worker` 的真实 HTTP 集成测试（仍 Mock 交易所）。  
3. 浏览器验证五个按钮与 Settings 持久化。  
4. 仍不要接真实 Hyperliquid。若下一步是执行层，应先在 worker 内按 PHASE 1 钉死的 v2.16.0 connector 做 **testnet/read-only** 设计，而不是开主网单。  
5. 策略 Runtime：先进程内加载 example_strategy，再考虑 sandbox 容器。

**停止。不进入 PHASE 3。**
