# STEP 4 报告 — 真实 Hyperliquid 账户只读同步验证

**Connector live：** `docs/STEP_4_AUTH_READONLY_REPORT.md`  
**Worker → Backend → SQLite 收口：** `docs/STEP_4_BACKEND_MIRROR_REPORT.md`（**VERIFIED**：live FLAT 已写入 `positions.source=exchange_mirror`）。未进入 STEP 5。

**状态：** STEP 4 接线完成并停止。未进入 STEP 5。未发送真实订单。未开启 `EXECUTION_ENABLED`。未伪造密钥冒充真实账户。  
**日期：** 2026-09-02  
**Hummingbot：** 官方镜像 `hummingbot/hummingbot:version-2.16.0`

标记：

- **VERIFIED**：本会话实际跑通
- **NOT VERIFIED**：未在该条件下运行
- **BLOCKED**：按规则停止（凭证缺失，或写路径风险已分析并拦住）
- **N/A**：本 STEP 禁止做的事

**是否自动进入下一阶段：否。**

---

## 本 STEP 只回答的问题

> 真实 Hyperliquid 账户状态能否安全地通过 Hummingbot v2.16.0 Connector  
> 进入 PositionGuard / Recovery / SQLite mirror，  
> 同时确保任何交易写操作仍然被彻底禁止？

**答案：**

| 半句 | 结论 |
| --- | --- |
| 写操作是否被彻底禁止 | **是。VERIFIED**（`EXECUTION_ENABLED=false` + `ReadOnlyGuard` + 实例级 `disable_exchange_write_loops`） |
| 账户状态进入 Guard / Recovery / mirror 的代码路径 | **已接线。VERIFIED**（Connector → Bridge DTO → Adapter → PositionGuard） |
| 真实账户 positions / orders / fills / user WS | **BLOCKED** — 本环境未提供 authenticated credential；未用 FakeConnector 冒充 |

未获得 `authenticated credential supplied`。`.env` 不存在。进程环境中地址/密钥均 unset。按规则不编造密钥、不连真实私有 API。

---

## 1. 账户连接结果

| 项 | 结果 |
| --- | --- |
| authenticated credential supplied | **否** |
| Docker secrets / 未跟踪 `.env` | **未发现** |
| 真实账户 `start_network(trading_required=True)` | **BLOCKED** |
| FakeConnector 冒充真实账户 | **未使用**（禁止） |

Factory 行为 **VERIFIED**：无凭证时仍走 `trading_required=False` 公开只读 Connector（STEP 3 路径）。有凭证时才会 `instantiate_authenticated` + 禁用 lost-order 撤单后再 `ReadOnlyGuard`。

凭证接入方式（均未跟踪，报告不写值）：

- 环境变量 `HYPERLIQUID_PERPETUAL_ADDRESS` / `HYPERLIQUID_PERPETUAL_SECRET_KEY`
- `*_FILE` 与 Docker secret 路径 `/run/secrets/hyperliquid_perpetual_*`
- 本地未跟踪 `.env`（`.gitignore` 已覆盖）

已提交的 `docker-compose.yml` **不**插值密钥，避免 `docker compose config` 把 secret 打进日志。

---

## 2. Hummingbot runtime

| 项 | 结果 |
| --- | --- |
| 官方镜像 `hummingbot/hummingbot:version-2.16.0` | **VERIFIED**（STEP 3 + 本 STEP Docker） |
| Worker 镜像 Python | **3.13.14**（官方 conda） |
| 本机 pytest | **3.14**；无 hummingbot 包（预期 skip） |
| 生产 `EXECUTION_MODE=hyperliquid` | **VERIFIED** |

架构未推翻：

```
Web UI → Backend / SQLite → TradingController → PositionGuard
  → HttpExecutionClient → Worker
    → Thin Adapter → ReadOnlyHummingbotBridge
      → ReadOnlyGuard → HyperliquidPerpetualDerivative v2.16.0
```

---

## 3. authenticated Connector

目标：`HyperliquidPerpetualDerivative(trading_required=True)` + `ReadOnlyGuard` + `EXECUTION_ENABLED=false`。

**源码分析 VERIFIED（官方镜像）：**

`ExchangePyBase.start_network` 在 `is_trading_required` 时会启动：

- trading rules / fees 轮询
- status REST 轮询
- **user stream**
- **`_lost_orders_update_polling_loop`**

`_cancel_lost_orders` 对每个 lost order 调用 `await self._execute_order_cancel(...)`。这是 **交易所撤单写操作**，发生在 **未包装的 `self` 上**，`ReadOnlyGuard` 看不到。

按 STEP 4 规则：**立即停止并分析，不得绕过安全限制。**

最小修复（不是重写 Hummingbot）：

1. 认证实例化之前调用 `disable_exchange_write_loops(raw)`。
2. `_cancel_lost_orders` → async no-op（lost-order 轮询不再撤单）。
3. `buy` / `sell` / `_place_order` / `cancel` / `_execute_order_cancel` / `set_leverage` 等在 **原始实例** 上改为抛 `ReadOnlyViolation`。
4. 再包 `ReadOnlyGuard`。
5. Factory 仍拒绝 `EXECUTION_ENABLED=true`。

未认证路径不调用 `trading_required=True` 的 `start_network`。  
带凭证的认证 `start_network`：**BLOCKED**（无 credential）。

Docker **VERIFIED**：在真实 v2.16.0 Connector 实例上，lost-order cancel 为 no-op；`buy` / `sell` / `_place_order` / `_execute_order_cancel` / `set_leverage` 全部 `ReadOnlyViolation`。

---

## 4. position

映射链（未自写交易所解析）：

Hyperliquid `clearinghouseState.assetPositions`  
→ Hummingbot `_update_positions` / `account_positions`  
→ Bridge `_asset_from_hb_position`  
→ `map_clearinghouse_positions`  
→ Adapter `PositionView`  
→ Backend `PositionGuard`

| 场景 | 结果 |
| --- | --- |
| LONG / SHORT / FLAT 映射（单元 + Fake 对照） | **VERIFIED** |
| symbol `BTC` → `BTC-USD` | **VERIFIED** |
| size / entry / side 符号规则（szi>0 LONG，szi<0 SHORT） | **VERIFIED** |
| 真实账户 `connector.account_positions` | **BLOCKED** |

无凭证时 Adapter 将 `account_read=skipped_no_user_address` 视为未认证，**不得**把空仓位当成交易所确认的 FLAT。

---

## 5. open orders

Hummingbot v2.16.0 Hyperliquid Connector 的 `in_flight_orders` 是 **本进程 OrderTracker**，不是账户全部挂单快照。`_update_orders` 只刷新已跟踪订单。本 STEP **没有**另写 `frontendOpenOrders` 客户端。

| 项 | 结果 |
| --- | --- |
| Bridge 读取 `in_flight_orders` → DTO | **VERIFIED**（stub / Fake） |
| 真实账户已有挂单进入 Worker | **NOT VERIFIED** / 无凭证 **BLOCKED** |
| SQLite 作为真相 | **否**（仍是 business mirror / audit） |

---

## 6. fills

Connector 成交来自 OrderTracker / user stream。`_update_trade_history` 只在存在 fillable in-flight orders 时拉 `user` trades，且忽略 tracker 中没有的成交。未建第二套 fill tracker。

| 项 | 结果 |
| --- | --- |
| Bridge `get_fills()` ← `_current_trade_fills` | **VERIFIED**（stub） |
| fill id / exchange trade id 映射 | **VERIFIED**（`tid` / `hash` → `map_hummingbot_fill`） |
| SQLite `uq_fills_exchange_fill_id` 去重 | **VERIFIED**（Backend） |
| 真实账户历史 fills | **BLOCKED** |

---

## 7. user WebSocket

v2.16.0：仅 `trading_required=True` 的 `start_network` 启动 `_user_stream_tracker_task` + `_user_stream_event_listener`。频道：`orderUpdates`、`user`。

本 STEP 不允许交易，因此不能用下单/撤单制造事件。

| 项 | 结果 |
| --- | --- |
| 源码：user stream 随 `trading_required=True` 启动 | **VERIFIED** |
| 真实 user stream 已建立 | **BLOCKED** |
| 认证失败时 Worker 不伪造成功 | **VERIFIED**（`start_network` 异常写入 recovery） |

若认证后 listener 未起来，Adapter 进入 **RECOVERING**（`has_user_stream` 为 false）。

---

## 8. MarketEvent

生产订阅（`connector.add_listener`）：

`OrderFilled` `OrderCancelled` `OrderFailure` `OrderUpdate` `TradeUpdate` `BuyOrderCompleted` `SellOrderCompleted`

只做：Hummingbot event → 项目 DTO（`map_market_event_kind`）→ mirror / audit。没有第二套事件状态机。

| 项 | 结果 |
| --- | --- |
| v2.16.0 `MarketEvent` 名称存在 | **VERIFIED** |
| 名称映射含 OrderUpdate / TradeUpdate | **VERIFIED** |
| 真实成交回调 | **NOT VERIFIED** |
| `OrderFailure` ≠ 可以重新开仓 | **VERIFIED**（映射为 `order_failure`；HB `failed` → 业务 **UNKNOWN**） |

---

## 9. Recovery

| 条件 | 行为 | 验证 |
| --- | --- | --- |
| foreign symbol 仓位 | `RECOVERING` + `FOREIGN_SYMBOL_POSITION`；不自动平仓 | 单元 **VERIFIED**；真实账户 **NOT VERIFIED**（账户无仓且禁止人为下单制造） |
| 查询失败 / 账户未知 | `account_state_unknown` → RECOVERING；不自动修成 FLAT | 代码路径 **VERIFIED**；真实失败 **NOT VERIFIED** |
| UNKNOWN 订单 | 禁止新开仓；不重新 place | Backend **VERIFIED**（既有） |
| user stream 异常 | 认证模式下 RECOVERING | 代码 **VERIFIED**；真实 WS **BLOCKED** |
| 有仓禁止 LONG/SHORT | PositionGuard | **VERIFIED** |
| Recovery 禁止开仓 | PositionGuard | **VERIFIED** |

Controller 对 foreign 只拒绝开仓，**不**调用 close。**VERIFIED**（源码：`has_foreign_positions` → Guard 拒绝）。

---

## 10. PositionGuard

| 规则 | 结果 |
| --- | --- |
| 有仓拒绝新 LONG/SHORT | **VERIFIED** |
| 反手禁止 | **VERIFIED** |
| Recovery 禁止开仓 | **VERIFIED** |
| foreign → 原因 `FOREIGN_SYMBOL_POSITION` | **VERIFIED** |
| SQLite FLAT + Connector LONG → 仍禁止开仓 | **VERIFIED** |

---

## 11. SQLite mirror

Exchange truth > Worker Connector > SQLite audit/mirror。Guard 使用 Controller 传入的交易所快照，不用本地仓覆盖交易所。

| 项 | 结果 |
| --- | --- |
| 本地 FLAT / 交易所 LONG 禁止开仓 | **VERIFIED** |
| 重复 fill 不双写 | **VERIFIED**（`exchange_fill_id` unique） |
| 真实 Connector LONG vs SQLite FLAT 的 live 对账 | **BLOCKED**（无账户） |

不一致时记 system/audit 事件：既有 RecoveryManager / AuditRepository 路径保留。本 STEP 无 live 冲突样本。

---

## 12. Exchange truth

生产 Adapter **不**把 `ExchangeStateStore` / `reconciliation.py` 当真相。刷新走 Connector `rest_snapshot` / `account_positions` / `in_flight_orders`。

无认证时空快照 **不是** “交易所确认无仓”。

---

## 13. ReadOnlyGuard

双保险 **VERIFIED**，不是只信 env：

1. `EXECUTION_ENABLED=false`（Compose / Dockerfile / factory 拒绝 true）
2. `ReadOnlyGuard` 拦截：`buy` `sell` `_place_order` `cancel` `set_leverage` `_execute_order_cancel` …
3. 实例级 `disable_exchange_write_loops` 拦住 HB 内部 lost-order **自动撤单**

Docker 真实 Connector：**Guard 五类 + `_execute_order_cancel` 均为 `ReadOnlyViolation`。**  
Adapter `place_order` 在只读下返回 REJECTED，不调用 `connector.place`。  
`cancel_order` / `set_leverage` 抛 `ExecutionDisabled`。

本 STEP **N/A**：place / cancel / close / open / reverse / `set_leverage` 实盘调用。

---

## 14. EXECUTION_ENABLED

全程 **false**。Factory 在 true 时 raise（即使 credential 环境变量被测试注入，仍先拒绝，**VERIFIED**）。未自动打开。未进入实盘。

---

## 15. 静态扫描

| 模式 | 结果 |
| --- | --- |
| Backend `import hummingbot` / `from hummingbot` | **无 VERIFIED** |
| Strategy `import hummingbot` | **无 VERIFIED** |
| Backend `OrderExecutor` / `PositionExecutor` | **无 VERIFIED** |
| Worker 生产 Adapter `self.connector.buy(` / `sell(` | **无 VERIFIED** |
| `renew_order` 实现 | **仓库无** |
| `hummingbot_place._place_order` | 仅 EXECUTION_ENABLED 路径；本 STEP 不可达 |
| lost-order 自动 `cancel` | 已 no-op + Guard |

---

## 16. 全部测试

| 套件 | 结果 |
| --- | --- |
| Worker 全量（含 Docker / STEP 2.5 / STEP 3 / STEP 4） | **69 passed, 2 skipped** |
| skip 1 | 本机 3.14 无 hummingbot 包（预期） |
| skip 2 | **BLOCKED: authenticated credential not supplied** |
| Backend 全量 | **42 passed** |

覆盖：Guard / Controller / Reservation / UNKNOWN / Recovery / Idempotency / Strategy isolation / cloid / Connector adapter / Docker runtime / ReadOnlyGuard / write-loop disable / `FOREIGN_SYMBOL_POSITION`。

未放宽断言。未用 FakeConnector 当作真实账户 PASS。

---

## 17. VERIFIED

- `EXECUTION_ENABLED=false` + factory 拒绝 true
- `ReadOnlyGuard` 拦 place / cancel / leverage / `_place_order` / `buy` / `sell`
- 真实 Connector 上 lost-order **自动撤单被禁用**
- 公开只读 Connector 路径（STEP 3）未破坏
- LONG / SHORT / FLAT 与 foreign → `FOREIGN_SYMBOL_POSITION` + RECOVERING + 零 close
- PositionGuard：交易所仓位优先于 SQLite；Recovery / UNKNOWN 禁止开仓
- fill 幂等 `exchange_fill_id`
- HB FAILED / OrderFailure → 业务 UNKNOWN，不能当“确定无单”
- Backend / Strategy 无 hummingbot
- `.env` / `secrets/` / `credentials/` / `docker-compose.override.yml` 被 gitignore
- 零真实订单

---

## 18. NOT VERIFIED

- 真实账户 FLAT / LONG / SHORT 三种 live 快照
- 真实 foreign symbol 仓位（禁止为测试而下单）
- 真实 `in_flight_orders` 与账户已有挂单是否一致（HB tracker 本就不做全账户挂单 hydrate）
- 真实 fills / user WS 推送 / MarketEvent 回调
- 真实 SQLite vs Connector 冲突审计样本
- 认证 `start_network` 在有密钥时的 builder fee / user stream 稳定性

---

## 19. BLOCKED

**真实账户只读同步**需要 Hyperliquid 地址 + 可签名 secret，且必须以不会进 Git 的方式提供。

- 本会话：**authenticated credential not supplied**
- 未伪造密钥
- 未对主网发私有 API
- 未把 FakeConnector 记为账户验证 PASS

另：**禁止**在未禁用 lost-order cancel 的情况下对生产调用 `trading_required=True` 的完整 `start_network`。该写路径已分析并拦住。

---

## 20. 风险

- 凭证一旦提供，认证 `start_network` 仍会连 Hyperliquid **私有** user WS / REST。那是只读同步，不是下单；仍须用户明确授权该网络访问。
- HB `in_flight_orders` ≠ 账户全部挂单。恢复流程不能把“tracker 为空”当成“交易所无挂单”。
- HB fills 绑定 in-flight tracker。历史成交可能对 Connector 不可见；不要为此再写一套 fill REST。
- 实例补丁依赖 Python 实例属性覆盖。Hummingbot 升级后必须重做 STEP 2.5 式源码核对。
- 误把无认证空仓当 FLAT 会违规开仓。当前未认证 recovery 文案保留。

---

## 21. 下一阶段建议

仅在用户明确下令后：

1. 以 **未跟踪** 方式提供 testnet 或主网 credential（报告只写 “authenticated credential supplied”），重跑 `test_step4_authenticated_readonly_account_or_blocked`。仍保持 `EXECUTION_ENABLED=false` + Guard + write-loop disable。只读观察 positions / orders / fills / user WS。
2. 若 live 显示 foreign 仓位：确认 RECOVERING + `FOREIGN_SYMBOL_POSITION`，**仍禁止**自动平仓。
3. **不要**进入 STEP 5 实盘。不要自动打开 `EXECUTION_ENABLED`。不要发送真实订单。

---

## 凭证与 Git

```
git check-ignore -v .env secrets/x credentials/x docker-compose.override.yml
```

均被 ignore。`git status` 无 `.env`、无 secret 文件。报告与源码无实际 secret。

---

## 是否允许进入下一阶段

**允许用户稍后开始 STEP 5 或授权只读 live 账户重跑。不允许本 Agent 自动进入。不允许自动开启 EXECUTION_ENABLED。不允许发送真实订单。**

---

## 停止

STEP 4 报告已写入。不开始 STEP 5。不索取 API secret。不发任何真实交易请求。
