# STEP 5 — MAINNET ONE-SHOT REPORT

**日期：** 2026-09-03  
**状态：已停止。** 这是一次性主网测试，不进入 STEP 6。

**STEP_5_RESULT = FAIL**

**账户上仍有真实 BTC-USD LONG。** 本轮已停止，没有发第三笔，没有再武装 Worker。平掉这笔仓需要你单独授权。

Compose / Dockerfile / `.env.example` 默认 `EXECUTION_ENABLED` 未改为 true。运行时武装仅用于本容器，结束后已 `docker rm`。

---

## 信号

| 项 | 值 |
| --- | --- |
| 实际信号 | LONG |
| strategy | ema5break |
| pair | BTC-USD |
| interval | 5m |
| signal candle timestamp | 1788438600000 |
| last bar | {"open": 77937.0, "high": 78436.0, "low": 77936.0, "close": 78308.0, "t": 1788438600000} |
| prev bar | {"open": 77960.0, "high": 77966.0, "low": 77925.0, "close": 77937.0, "t": 1788438300000} |
| 伪造信号 | 否 |

---

## OPEN

| 项 | 值 |
| --- | --- |
| OPEN cloid | 0x843ccebd016d4445b4877c5a7f458ca0 |
| OPEN order ID | 534953821022 |
| OPEN 状态 | 交易所已成交并留下仓位；本地后来被标成 UNKNOWN（CLOSE 前 cancel 返回 403，未重发） |
| OPEN 实际成交数量 | 0.00013（交易所仓位，SQLite fills 为空） |
| OPEN 实际成交价格 | 78352.0（交易所 entry） |
| accepted | True |

---

## CLOSE

| 项 | 值 |
| --- | --- |
| CLOSE cloid | 0x9b81cf27d36e432da84bff99fe3e59c9 |
| CLOSE order ID | None |
| CLOSE 状态 | REJECTED（`notional 9.67707 below minimum 10`）。IOC 卖价按 mid×0.95 计价，名义掉到 $10 以下；未重交 CLOSE。 |
| CLOSE 实际成交数量 | 无 |
| CLOSE 实际成交价格 | 无 |

---

## 最终交易所状态

| 项 | 值 |
| --- | --- |
| 最终 BTC-USD position | LONG size=0.00013 |
| 最终账户余额 equity | 15.033865 |
| 最终账户余额 available | 11.642425 |
| real orders submitted | 2 |
| UNKNOWN 是否发生 | 是（OPEN 本地单在 cancel 403 后被标 UNKNOWN；未把 UNKNOWN 当成交失败去重发） |
| Recovery 是否发生 | False |
| foreign position 是否发生 | False |
| execution_enabled 最终状态 | False |
| bridge_armed 最终状态 | False |
| stop_reason | not_flat_after_close |

---

## 路径与禁止项

- 下单路径：ema5break → TradingController → HttpExecutionClient → Worker → Adapter → armed Bridge → Hummingbot v2.16.0 → Hyperliquid
- buy/sell/cancel/set_leverage/直接 HTTP 下单：**未作为本脚本路径**
- 自动反手：否
- 默认 Compose/Dockerfile EXECUTION_ENABLED：false

```json
{
  "strategy": "ema5break",
  "signal": "LONG",
  "signal_meta": {
    "event": "SIGNAL_READY",
    "signal": "LONG",
    "closed_t": 1788438600000,
    "last_bar": {
      "open": 77937.0,
      "high": 78436.0,
      "low": 77936.0,
      "close": 78308.0,
      "t": 1788438600000
    },
    "prev_bar": {
      "open": 77960.0,
      "high": 77966.0,
      "low": 77925.0,
      "close": 77937.0,
      "t": 1788438300000
    }
  },
  "pair": "BTC-USD",
  "execution_enabled_compose_default": false,
  "buy_sell_called": false,
  "cancel_called": false,
  "set_leverage_called": false,
  "unknown": false,
  "recovery": false,
  "foreign_seen": false,
  "duplicate_orders": false,
  "auto_reverse": false,
  "bridge_armed_final": false,
  "STEP_5_RESULT": "FAIL",
  "worker_health_before_start": {
    "execution_enabled": true,
    "worker_state": "NOT_READY",
    "recovery_reason": null
  },
  "start": {
    "ok": true,
    "state": "RUNNING"
  },
  "preflight": {
    "authenticated_worker_state": "READY",
    "execution_enabled": true,
    "recovery_reason": null,
    "btc_side": "FLAT",
    "foreign": [],
    "open_order_precheck": {
      "status": "VERIFIED",
      "source": "hyperliquid_info_openOrders_via_connector_api_post",
      "configured_pair": "BTC-USD",
      "configured_open_count": 0,
      "other_open_count": 0,
      "other_coins": [],
      "persisted": false,
      "blocking": false,
      "error_type": null
    },
    "available": "15.049705",
    "system_state": "RUNNING"
  },
  "open": {
    "accepted": true,
    "reason": "OPEN",
    "signal_id": "ee9d4d45-7a2a-43e6-8452-829c388c5eb9",
    "cloid": "0x843ccebd016d4445b4877c5a7f458ca0",
    "status": "OPEN"
  },
  "position_after_open": {
    "symbol": "BTC-USD",
    "side": "LONG",
    "size": "0.00013",
    "entry_price": "78352.0",
    "unrealized_pnl": "0.00182"
  },
  "orders": [
    {
      "id": "c21df242-3164-403a-a388-2fdd1a6ba994",
      "intent_id": "1ed93a82-b23c-4d7d-a294-1ee6d99bbb8e",
      "request_id": "e9348f86-bdf5-4205-8dc0-72fa50b2a26b",
      "cloid": "0x9b81cf27d36e432da84bff99fe3e59c9",
      "exchange_oid": null,
      "symbol": "BTC-USD",
      "side": "SELL",
      "order_type": "MARKET",
      "quantity": "0.000130000000",
      "reduce_only": true,
      "status": "REJECTED",
      "signal_id": "73b017a3-d36f-42cf-b2f8-dfcff8dcc5c3",
      "error_message": "notional 9.67707 below minimum 10",
      "created_at": "2026-09-03T12:39:46"
    },
    {
      "id": "9d22704c-db62-41f4-b307-f29649894d7b",
      "intent_id": "3d085bd3-1155-4796-a5bb-32171281fc65",
      "request_id": "8abbc797-305b-43d4-b9c2-8261f49ad621",
      "cloid": "0x843ccebd016d4445b4877c5a7f458ca0",
      "exchange_oid": "534953821022",
      "symbol": "BTC-USD",
      "side": "BUY",
      "order_type": "MARKET",
      "quantity": "0.000134014616",
      "reduce_only": false,
      "status": "UNKNOWN",
      "signal_id": "ee9d4d45-7a2a-43e6-8452-829c388c5eb9",
      "error_message": null,
      "created_at": "2026-09-03T12:39:16"
    }
  ],
  "fills": [],
  "close": {
    "ok": true,
    "cloid": "0x9b81cf27d36e432da84bff99fe3e59c9",
    "status": "REJECTED"
  },
  "final_position": {
    "symbol": "BTC-USD",
    "side": "LONG",
    "size": "0.00013",
    "entry_price": "78352.0",
    "unrealized_pnl": "-0.01144"
  },
  "final_balance": {
    "equity": "15.033865",
    "available": "11.642425",
    "margin_used": "3.391440"
  },
  "final_status": {
    "position": {
      "symbol": "BTC-USD",
      "side": "LONG",
      "size": "0.00013",
      "entry_price": "78352.0",
      "unrealized_pnl": "-0.01144"
    },
    "worker": "READY",
    "system_state": "RUNNING"
  },
  "stop_reason": "not_flat_after_close",
  "worker_health_after": {
    "execution_enabled": false,
    "worker_state": "STOPPED"
  }
}
```
