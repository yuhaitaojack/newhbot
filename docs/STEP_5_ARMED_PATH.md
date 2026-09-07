# STEP 5 ARMED PATH — 代码准备（未授权实盘）

**状态：代码闸门已落地并停止。** 未连接主网写。未 place / cancel / leverage。未修改 `.env`。未把默认 `EXECUTION_ENABLED` 改为 true。  
**日期：** 2026-09-03

本文件不是实盘授权。正式「一开一平」仍须用户在当前会话明确确认。

---

## 修改了什么

1. **Factory** 去掉无条件 `RuntimeError`。`EXECUTION_ENABLED=true` 且 **无凭证** 仍拒绝。有凭证时可以构建 armed Bridge。默认仍 `false`。
2. **`disable_exchange_write_loops`** 仍 patch 裸实例的 `_place_order` / buy / sell / cancel / leverage，lost-order 仍 no-op。额外把原始 `_place_order` 存到 `_newhbot_original_place_order`。
3. **`ReadOnlyHummingbotBridge.place`**：仅 `execution_enabled=True` 时，经 `_ArmedPlaceTarget` + `place_with_injected_cloid` 调用**已保存的**原始 `_place_order`。`buy()`/`sell()`、cancel、leverage、Guard 上的 `_place_order`、patch 后的 raw `_place_order` 仍禁止。
4. **Adapter**：`execution_enabled=false` 仍 DRY_RUN。`read_only` 且未 armed 仍拒单。armed 时才 `connector.place(wire)`。cancel / set_leverage 仍因 `read_only` 拒绝。UNKNOWN 不重发逻辑未改。
5. **`place_with_injected_cloid`**：拒绝经 `ReadOnlyGuard` 调用；要求 `0x` 业务 cloid。

未改：Compose / Dockerfile / `.env.example` 默认 `false`、Backend、策略、杠杆。

---

## 为什么不会绕过现有安全保护

- 默认进程：`enabled=false` → Adapter 在调用 Connector 前 REJECTED。
- 即使误开 env：无凭证 Factory 不起进程；有凭证也必须走 Worker RPC ← Controller，不能经 Guard 调 `_place_order`，不能 `buy()`/`sell()`。
- lost-order 内循环仍打 patch 后的 `_place_order`（raise）和 `_cancel_lost_orders`（no-op）。
- 武装 shim **没有** buy/sell；只有保存的 `_place_order`。
- Recovery / UNKNOWN / disconnected / foreign / Exchange>SQLite / Backend 不 import hummingbot：未改。

---

## false 状态下测试结果

- Worker 非交易：**66 passed, 3 skipped**（docker / 无本地 hummingbot）
- Backend 非交易：**48 passed**
- 未跑 live docker 写探针（禁止）

---

## 真实下单路径是否 READY

**代码 READY，部署未武装，未经授权不得使用。**

完整链已接线：

`TradingController → HttpExecutionClient → Worker /rpc/place_order → Adapter → Bridge.place → 注入 cloid 的原始 _place_order`

但当前 Compose / 默认配置仍是 `EXECUTION_ENABLED=false`。打开它并发送订单 **不是** 本轮允许的操作。

---

## 是否还有必须修复的问题

**无阻塞本代码准备的必须项。** 正式授权前仍须：

- 会话确认主网/testnet 与「允许发送这一笔」
- Compose 挂未跟踪凭证（现在默认没挂）
- 测完立刻改回 `false`
- 紧急停止的 **cancel** 仍禁止；最小「一开一平」用 reduce-only **place**（CLOSE）

---

## 停止

等待用户明确授权后再连接主网或发送真实订单。
