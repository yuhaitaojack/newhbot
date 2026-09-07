# STEP 3 — DISARM EXECUTION WORKER

**日期：** 2026-09-04  
**授权：** 用户在本会话明确授权：只停止并删除一次性 execution-worker 容器，不进行任何交易。  
**性质：** 运维解除武装。未开仓、未平仓、未撤单、未设杠杆、未启动策略/oneshot/frontend、未启动新 worker、未修改 Compose / Dockerfile / `.env` 默认值、未 git commit。  
**本文件不含** API secret / 私钥。

**STEP_3_RESULT = PASS**

---

## 1. 执行前状态

本机当时 **Docker Desktop 未运行**，`docker` 客户端连不上 `dockerDesktopLinuxEngine`。

| 检查 | 结果 |
| --- | --- |
| `127.0.0.1:8001` | 已不可达（curl exit 7） |
| `127.0.0.1:8000` | 已不可达（host backend 进程不在） |
| `:5173` / `:8080` | 无监听 |
| 交易相关进程 | 无 uvicorn / python worker |

为执行用户指定的 `docker rm -f`，本 STEP **只启动了已安装的 Docker Desktop 引擎**，没有 `docker run`、没有 `docker compose up`。

引擎就绪后容器清单：

| 项 | 值 |
| --- | --- |
| 名称 | **`newhbot-step5-oneshot-worker`**（确认匹配） |
| 镜像 | `newhbot-execution-worker:step4` |
| 状态 | `Exited (255)` |
| 端口绑定 | `127.0.0.1:8001->8001/tcp`（已退出，未在监听） |
| RestartPolicy | **`no`** |
| `StartedAt` | 2026-09-03T12:52:13Z |
| `FinishedAt` | 2026-09-04T04:32:21Z（Docker 引擎本次拉起时记为异常退出） |
| 运行时 `EXECUTION_ENABLED` | 曾为 **true**（容器内环境；未改镜像/Compose/`.env` 默认） |

无其它容器。无 compose 项目在跑。

---

## 2. 停止并删除

命令：

```text
docker rm -f newhbot-step5-oneshot-worker
```

输出：

```text
newhbot-step5-oneshot-worker
```

退出码 0。

之后：

```text
docker ps -a
CONTAINER ID   IMAGE     COMMAND   CREATED   STATUS    PORTS     NAMES
```

空。`docker compose ls` 无项目。

未启动替代 worker。未改 Compose / Dockerfile / `.env`。

---

## 3. 只读验证

### 3.1 Worker 端口

`GET http://127.0.0.1:8001/health`

```text
curl: (7) Failed to connect to 127.0.0.1 port 8001 after 2033 ms: Could not connect to server
```

**8001 不再可访问。**

### 3.2 Backend HTTP

`GET http://127.0.0.1:8000/api/status`

```text
curl: (7) Failed to connect to 127.0.0.1 port 8000 after 2036 ms: Could not connect to server
```

Backend **进程未在跑**（STEP 2 时是 host uvicorn；本会话开始前已不在）。本 STEP **没有**重启 backend（避免它去连已删除的 worker，也避免任何交易路径）。

持久化库 `data/step5_oneshot.db`（STEP 2 CLOSE 写入，只读打开）：

| 项 | 值 |
| --- | --- |
| `system_state` | **STOPPED** |
| `trading_enabled` | **0 / false** |
| `estop` | 0 / false |
| `close_intent` | null |
| `updated_at` | 2026-09-03 13:19:09 UTC |

与 STEP 2 结束后的控制面一致：**保持 STOPPED，且 `trading_enabled=false`。**

### 3.3 交易所仓位 / 挂单

本 STEP 已删除 worker，**禁止**再起 worker，**禁止**直连 Hyperliquid。因此 **不能** 再做 live `GET /rpc/position` 或 `GET /rpc/open_orders`。

证据链：

| 来源 | 结果 |
| --- | --- |
| STEP 2 实盘 GET（worker 仍在时） | BTC-USD **FLAT**，`open_orders=[]` |
| 本地镜像 `positions`（只读 SQLite） | BTC-USD **FLAT** size 0，`source=exchange_mirror`，`updated_at=2026-09-03 13:19:02` |
| 本 STEP 写接口 | **无**（未 place/close/cancel/set_leverage） |

没有新的下单或开仓动作去改变交易所状态。

---

## 4. 禁止项核对

| 禁止 | 本 STEP |
| --- | --- |
| 修改 Compose / Dockerfile / `.env` 默认值 | 未改 |
| 启动新的 worker | 未启动 |
| 启动 frontend | 未启动 |
| `place_order` / close / cancel / set_leverage | 未调用 |
| 启动策略或 oneshot 脚本 | 未启动 |
| git commit | 未提交 |

为删除容器而启动 Docker Desktop 引擎；引擎起来后该容器是 `Exited` 且 `RestartPolicy=no`，随后被 `rm -f`，没有重新 `docker run`。

---

## 5. 结论

一次性武装容器 **`newhbot-step5-oneshot-worker` 已删除**。`127.0.0.1:8001` 不可访问。backend 控制面持久化为 **STOPPED** / **`trading_enabled=false`**，HTTP API 也未在监听。未进行任何交易。

**STEP_3_RESULT = PASS**

---

## 6. 后续（用户授权：清空 Docker 并按 Compose 默认重新部署）

**日期：** 2026-09-04（同日稍后）

用户明确要求：清除 Docker 中的部署，再按本项目所需重新部署，然后继续验证。未改 Compose / Dockerfile / `.env` 默认值。未 git commit。未调用 place/close/cancel/set_leverage。未点 UI「启动」。

### 6.1 清除

- `docker rm -f tender_wing`（Docker 引擎起来后冒出的同镜像容器；未映射主机 8001）
- `newhbot-step5-oneshot-worker` 此前已删除，未再出现
- 清除后 `docker ps -a` 为空

未执行通配 `docker rm -f $(docker ps -aq)` / `docker system prune`。未删镜像。

### 6.2 重新部署

`docker compose up -d --build` 首次因 Docker Hub 超时失败。随后：

- 本地已有 `newhbot-execution-worker:step4`，tag 为 `newhbot-execution-worker`，**未**再拉 hummingbot 基座、**未**把 `EXECUTION_ENABLED` 改为 true
- 构建并启动 `backend`、`frontend`
- `docker compose up -d --no-build`

运行中：

| 容器 | 主机端口 | 武装 |
| --- | --- | --- |
| `newhbot-execution-worker-1` | **不发布** 8001（仅 `8001/tcp`） | `EXECUTION_ENABLED=false` |
| `newhbot-backend-1` | `127.0.0.1:8000` | `EXECUTION_MODE=mock`，`EXECUTION_ENABLED=false` |
| `newhbot-frontend-1` | `127.0.0.1:8080` | UI only |

Worker 容器内 `GET /health`：

```json
{"status":"ok","mode":"hyperliquid","connected":false,"ready":false,"worker_state":"NOT_READY","execution_enabled":false,"trading_pair":"BTC-USD","ws_connected":false,"sync_status":"NONE","hummingbot_version":"v2.16.0","recovery_reason":null,"foreign_symbols":[]}
```

主机 `GET http://127.0.0.1:8001/health`：仍不可达（curl 7）。

Backend `GET /api/status`（Compose 使用 `./data/newhbot.db`，不是 STEP 5 的 `step5_oneshot.db`）：

- `system_state=STOPPED`
- `trading_enabled=false`
- `worker_state=NOT_READY`
- 本地镜像 position **FLAT**（worker `connected=false`，本轮**没有**再查 Hyperliquid 实盘）

UI Dashboard / Settings 已打开：STOPPED，未点启动/平仓/紧急停止。

武装 oneshot worker **没有**回来。当前 worker 是 Compose 默认的 **DRY / 未武装** 实例。
