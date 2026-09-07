# STEP 5 — 只读主网 PRE-FLIGHT + ema5break 策略文件

**状态：本轮完成并停止。** 未发送真实订单。未把 Compose / Dockerfile / `.env.example` 的 `EXECUTION_ENABLED` 改为 true。未进入「一开一平」实盘。  
**日期：** 2026-09-03  
**Hummingbot：** 官方镜像 `hummingbot/hummingbot:version-2.16.0`（本轮用本地 `newhbot-execution-worker:step4` + 绑定当前 `execution-worker/app`）  
**性质：** READ-ONLY MAINNET PRE-FLIGHT + 策略文件落地

标记：

- **VERIFIED**：本会话实际跑通
- **NOT VERIFIED**：未在该条件下观察到
- **BLOCKED**：按规则或环境停止
- **N/A**：本轮禁止做的事

**是否自动进入真实开仓：否。** 本文件不是实盘授权。

---

## 结论

Docker Desktop 引擎已起来。只读主网探针在 `EXECUTION_ENABLED=false` 下跑通：认证账户 **BTC-USD = FLAT**，写路径仍被 Guard 全部拦住。

交易策略 **ema5break** 已写成策略文件（只输出 `LONG` / `SHORT` / `CLOSE` / `HOLD`），并作为默认 `active_strategy`。K 线自动循环与 `StrategyRuntime.evaluate()` 仍未接到该文件；**不得把本轮当成策略已在实盘跑。**

本轮 **未发生任何真实交易写操作**（未 place / cancel / set_leverage / buy / sell）。

---

## PRE-FLIGHT 检查表

| 项 | 标记 |
| --- | --- |
| Docker Desktop 引擎 | **VERIFIED** Server `29.7.2` |
| 未跟踪 `.env` 存在 | **VERIFIED** |
| `.env` 中 `EXECUTION_ENABLED` | **false VERIFIED** |
| address / secret 已提供（不打印值） | **VERIFIED** authenticated credential supplied |
| Compose / Dockerfile / `.env.example` 默认仍为 false | **VERIFIED** |
| 从 Docker Hub 重建 `step5-preflight` 镜像 | **BLOCKED**（`auth.docker.io` 超时） |
| 回退：`newhbot-execution-worker:step4` + 只读挂载当前 `app/` | **VERIFIED** `registry_build=false`，`current_app_bind_mounted=true` |
| 认证 REST / `account_read=authenticated` | **VERIFIED** |
| `worker_state` | **VERIFIED = READY** |
| `recovery_reason` | **VERIFIED = null** |
| 配置对 BTC-USD | **VERIFIED = FLAT** size `0` |
| foreign symbols | **VERIFIED 本快照无** |
| `one_way_ok` | **VERIFIED true** |
| `bridge_armed` | **VERIFIED false** |
| `write_loops_disabled` | **VERIFIED true** |
| Guard：`buy` / `sell` / `_place_order` / `cancel` / `set_leverage` / `_execute_order_cancel` | **VERIFIED** 全部 `ReadOnlyViolation` |
| lost-order `_cancel_lost_orders` | **VERIFIED** no-op（未抛错） |
| `_newhbot_original_place_order` 已保存 | **VERIFIED true**（武装路径代码在，默认未开） |
| BTC-USD `trading_rules` | **VERIFIED** 刷新后 `511` 条，含 BTC-USD |
| tick / step / min size / min notional | **VERIFIED** `0.1` / `0.00001` / `0.00001` / `10` |
| Connector `open_order_count` | **VERIFIED 0**（进程 tracker） |
| tracker 空 = 交易所无挂单 | **否。不得如此解释** |
| 账户权益 / 可用余额 | **NOT VERIFIED**（见下文） |
| 真实 LONG / SHORT 快照 | **NOT VERIFIED**（当前无仓；禁止为测试开仓） |
| 全账户挂单簿 | **NOT VERIFIED** |
| Backend → Worker Compose 联调 / UI `8080` | **NOT VERIFIED**（本轮未 `docker compose up`） |
| 真实 place / CLOSE | **N/A — 未执行** |

---

## 凭证与安全

- 报告用语：**authenticated credential supplied**
- secret **未**写入源码、yaml、json、Dockerfile、测试、本报告
- 仅存在于未跟踪 `.env`；探针用临时文件挂进容器 `/run/secrets/...`，跑完删除
- 探针 JSON 不含地址或密钥（泄漏检查通过）
- `EXECUTION_ENABLED` 进程内与 Compose 默认均为 **false**
- 探针 `bridge_armed=false`：即使代码里已有武装 place 闸门，本轮也未打开

---

## 1. Docker Hub 重建失败（环境）

本机 `docker build` 拉 `hummingbot/hummingbot:version-2.16.0` 失败：

`auth.docker.io` OAuth token TCP 443 超时。

因此 **没有** 打出 `newhbot-execution-worker:step5-preflight`。

只读探针改为：

1. 使用已有 `newhbot-execution-worker:step4`（仍基于官方 v2.16.0）
2. 把当前仓库 `execution-worker/app` **只读绑定**到 `/app/app`
3. 运行当前 `step5_preflight_probe.py`
4. 容器环境 `EXECUTION_ENABLED=false`

这覆盖了当前 Worker 代码路径，但 **不是** 一次全新 registry 构建。下次能访问 Docker Hub 时应再打 `step5-preflight` 镜像确认。

---

## 2. 认证账户快照

**VERIFIED**（仓位路径）

| 项 | 值 |
| --- | --- |
| `authenticated` | true |
| `account_read` | authenticated |
| `account_connection` | VERIFIED |
| BTC-USD | **FLAT** |
| 非零仓位 `position_symbols` | `[]` |
| foreign | 无 |

FLAT 来自认证后的交易所仓位，不是把查询失败当成空仓。查询失败时探针会把 `configured_side` 标成 `UNKNOWN` 并退出。

LONG / SHORT / 真实 foreign：**NOT VERIFIED**。

### 权益映射缺口

探针读到 `equity=0`、`available=0`。这 **不能** 当成账户真的是 0 USDC，也 **不能** 当成已核实有足够 `$10` 名义金。

原因：`ReadOnlyHummingbotBridge.rest_snapshot()` 里 `"account": {}` 写死为空，Adapter `get_balance()` 只能得到默认 0。

**账户保证金 / 可开仓名义：NOT VERIFIED。** 正式一开一平前必须补上 Connector 余额字段映射，或另用认证 clearinghouse 快照核对，禁止用这个 0 做资金结论。

### 挂单

`open_order_count=0` 只是 Hummingbot **in-flight tracker**。HB v2.16.0 不会 hydrate 全账户挂单。开仓前仍须用认证账户查询交叉确认，不能把 tracker 空当成盘面无单。

---

## 3. 写保护（本轮再次确认）

在 `start_network` 之后、只读查询期间：

| 调用 | 结果 |
| --- | --- |
| `buy` / `sell` | ReadOnlyViolation |
| `_place_order` | ReadOnlyViolation |
| `cancel` / `_execute_order_cancel` | ReadOnlyViolation |
| `set_leverage` | ReadOnlyViolation |
| `_cancel_lost_orders` | no-op |

Adapter 未走 armed `place`。`EXECUTION_ENABLED=false`。

---

## 4. 策略 ema5break

以后实盘测试用这个策略名：**ema5break**。

| 文件 | 作用 |
| --- | --- |
| `strategies/ema5break/strategy.py` | 纯信号 `on_bar(snapshot) -> LONG\|SHORT\|CLOSE\|HOLD` |
| `strategies/ema5break/manifest.yaml` | BTC-USD、5m、期望杠杆 3、参数默认值 |
| `backend/tests/test_ema5break_strategy.py` | 包线开仓、禁反手、ATR 止损 CLOSE |

规则（与需求对齐）：

- 市场：BTC 永续；设置项杠杆 **3x**（策略 **从不** `set_leverage`）
- 周期：5 分钟 K 线
- 最多一仓；有仓只允许 `HOLD` / `CLOSE`，禁止把反向包线当成反手
- 做多：阳包阴，且阳线收盘价 **高于 EMA5**，在该根收盘发 `LONG`
- 做空：阴包阳，且阴线收盘价 **低于 EMA5**，发 `SHORT`
- 止损距离：`2 * ATR`；止盈距离：止损的 `1.5` 倍（即距开仓 `3 * ATR`）

Backend：

- 空库或仍为 `example_hold` 时，seed 写入 `ema5break` 并设 `active_strategy=ema5break`、`trading_pair=BTC-USD`、`leverage=3`
- `GET /api/strategy` 返回 **当前 active** 策略的参数（`ema_period` 等），不再误用列表里最新/另一条版本

**未接线（必须写明）：**

- `backend/app/strategy/runtime.py` 的 `evaluate()` 仍固定返回 `HOLD`
- 没有 5m K 线订阅、没有自动把 `on_bar` 送进 TradingController
- 因此 **策略实盘评估 = NOT VERIFIED**

单元测试（本轮）：

- `strategies/ema5break` + Backend API / Guard：**53 passed**
- 未削弱断言

---

## 5. 本轮明确没做

- 未设置 `EXECUTION_ENABLED=true`
- 未 `POST /api/trading/signal` 真实 LONG/SHORT/CLOSE
- 未改杠杆到交易所 3x（Controller 仍不调用 `set_leverage`）
- 未启动 `docker compose up`（UI `http://127.0.0.1:8080` 本轮未验证）
- 未引入 Hummingbot Strategy V2 / Executor / Controller
- 未开始下一阶段的连续自动交易

---

## 正式一开一平之前仍缺

1. 当前会话再确认一句：**允许发送这一笔真实主网订单**（开 + 平）。
2. 临时覆盖 Worker `EXECUTION_ENABLED=true`，测完立刻改回 false。
3. 补上真实账户权益映射，确认名义 ≥ `$10`（`min_notional=10` **VERIFIED**）。
4. 认证交叉确认无 foreign、无未跟踪挂单；BTC-USD 仍 FLAT。
5. 信号必须经 **TradingController**；禁止脚本直打 Connector。
6. 紧急停止的 **cancel** 仍禁止；平仓用 reduce-only **place**（`CLOSE`）。
7. 不要打开 ema5break 自动循环，直到单笔路径证明完成。

`AGENTS.md` 仍适用：最多一仓、禁反手、Exchange > SQLite、Recovery 禁开、密钥不进 Git。

---

## 停止

等待用户明确授权后再连接主网写或发送真实订单。
