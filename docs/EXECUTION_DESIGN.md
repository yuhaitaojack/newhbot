# 执行层设计（Hyperliquid 永续）

未在 testnet 下过单。下列「已验证」指官方文档或 v2.16.0 连接器源码；「未确认」留给 PHASE 2 POC。

## 1. 接口对照

官方：

- REST info：https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- 永续 info：https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
- 交易：https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint
- WS：https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket
- 订阅：https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- nonce：https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets
- 错误：https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses

| 能力 | Hyperliquid | Hummingbot connector v2.16.0 |
| --- | --- | --- |
| Market | 文档有 trigger `isMarket` 以及 IOC 限价；连接器用 **IOC 限价 ±5%** 模拟市价 | 已读源码 |
| Limit | `tif`: Alo / Ioc / Gtc | LIMIT=Gtc，LIMIT_MAKER=Alo |
| Position mode | WS 类型 `AssetPosition { type: "oneWay" }` | 仅 ONEWAY |
| Leverage | `updateLeverage` `{asset, isCross, leverage}` | 已封装；默认 cross |
| Size | `sz` 字符串；步长 `szDecimals` | `10**-szDecimals` |
| Margin | `clearinghouseState` 的 marginSummary / isolated 字段 | 同步持仓时读取 leverage.type |
| Reduce only | 订单字段 `r` / `reduceOnly` | `PositionAction.CLOSE` → true |
| Close | 无单独 close-all API；对仓位反向 reduce-only | 由我们发 CLOSE |
| Order ID | `oid` uint64 | 回报里取 `resting`/`filled`.oid |
| Client order ID | 可选 128-bit hex `c`/`cloid` | MD5(HBOT id) → `0x`+32hex |
| 状态查询 | `orderStatus`，`oid` **或 cloid** | 连接器也用 orderStatus |
| Fill | WS `userFills` / userEvents fills | `_process_trade_message` |
| Partial | 订单 `sz` 剩余；多次 fill | 连接器 TradeUpdate |
| Cancel | `cancel` (oid) 或 `cancelByCloid` | 源码 `type:cancel` + cloid 字段（**与官方 action 名是否一致未运行验证**） |
| Unknown | 无回报时用 info 查 | `UNKNOWN_ORDER_MESSAGE` |
| 断线 | 官方要求自动重连；snapshot `isSnapshot`；漏数据用 info 补 | WS timeout 60s / heartbeat 30s |
| 精度 | 价格 tick + 最多 5 位有效数字；名义 ≥ $10 | #8356 量化修复；MIN_NOTIONAL 10 |
| 杠杆上限 | `maxLeverage` per coin（meta / 持仓里有） | 设置失败会返回 error 字符串 |

## 2. 防止「超时后重复开仓」

这是执行层第一风险。HL **nonce 不能重复**；**cloid 应按用户唯一**。但 Hummingbot `buy()` 每次都新建 cloid，**重试 buy() 不是幂等**。

可靠流程：

```
1. Guard 通过（交易所 FLAT，本地 FLAT）
2. 生成 intent_id
3. 生成确定性 cloid = 128-bit hex（例如 UUID 去掉横线加 0x）
4. INSERT orders(intent_id, cloid, side, qty, status=UNKNOWN) COMMIT
5. Worker.place(cloid, ...)   // 禁止在 Worker 内再随机生成 cloid
6a. 同步成功 → 写入 oid，status=OPEN/FILLED
6b. HTTP 超时 / 进程崩溃
    → 禁止步骤 5 的第二次调用
    → REST POST /info {type:orderStatus, user, oid: cloid}
    → 同时 GET clearinghouseState 与 openOrders
    → 若订单存在或已有仓：更新本地，结束 UNKNOWN
    → 若 orderStatus 显示从未存在 且 仓仍 FLAT 且 无挂单：
         仍保持 UNKNOWN 或标记 FAILED 需人工；
         「从未存在」与「还没上链」无法用一次查询绝对区分
         → 冷却后最多再查 N 次，不得换 cloid 重发
         → 若官方/实测确认「重复 cloid 会被拒」则可安全用同一 cloid 重放一次
           （PHASE 2 必须在 testnet 验证重复 cloid 行为）
```

**在重复 cloid 行为未确认前：超时后只查询，不重发。** 这可能漏掉「请求根本没到服务器」的开仓，但不会双开。漏单可由用户再等下一根 `LONG`（仍要 Guard）。宁可漏、不可双。

平仓同样：先记 UNKNOWN 的 reduce-only cloid，超时只查询。

## 3. 开仓 / 平仓订单形态（设计选择）

- 开仓：默认 **MARKET 语义** = connector 的 IOC 限价 ±5%。若滑点过大被 `IocCancel` / `oracleRejected`，记失败，**不加码重试成 GTC**（GTC 会留下挂单，破坏「最多一仓」的清晰度）。
- 平仓：reduceOnly=true 的同样 IOC。若部分成交：继续对剩余仓位发 reduce-only，直到 `szi==0` 或进入 RECOVERY。
- 不使用 `grouping: positionTpsl` 作为 v1 机制（策略自己发 CLOSE）。

## 4. 精度

下单前必须用最新 `metaAndAssetCtxs`：

- `sz` 对齐 `szDecimals`
- 价格走连接器 `quantize_order_price`
- 名义 `px * sz >= 10` USD

规则缓存在 Worker，但开仓前若 SYNC 过期则刷新。

## 5. Worker 窄接口

```
connect() / health()
get_position(pair) -> FLAT|LONG|SHORT + szi + entry + leverage
get_open_orders(pair)
get_order_status(cloid)
place(cloid, side, qty, type, reduce_only, price?)
cancel(cloid)
set_leverage(pair, leverage)   # 仅设置，不在策略里调用
subscribe_events() -> fills/orders/positions
```

没有 `reverse()`，没有 `ensure_position()`。

## 6. 密钥

Worker 使用 Hyperliquid **API wallet**（agent），查询账户时用 **master address**（官方：用 agent 地址查会得到空结果）。密钥不进 Backend SQLite。testnet 与 mainnet 配置隔离。
