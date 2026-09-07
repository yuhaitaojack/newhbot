# PHASE 140 REPORT

日期：2026-09-06

## 目标

为完整实盘准备一个清晰且固定 testnet 的显式执行配置入口，同时保持默认 Compose 安全。

## 完成项

- 新增 `docker-compose.testnet-live.example.yml`。
- 该文件固定 `HYPERLIQUID_DOMAIN=hyperliquid_perpetual_testnet`，无法通过它切换主网。
- 仅显式合并该 override 时启用 `EXECUTION_ENABLED=true`。
- 强制要求外部提供 testnet 地址、私钥和控制 token；仓库不包含任何真实值。
- 默认 `docker compose` 文件未改变，仍为 Mock/执行关闭。

## 验证

- 缺少 `CONTROL_API_TOKEN` 时 Compose 配置渲染明确失败。
- 使用占位变量渲染成功，确认 Worker/Backend 均为 hyperliquid、testnet、execution=true。
- 本阶段未启动该 override，未连接交易所写接口，未发送订单。

## 当前边界

下一步可在当前会话明确确认后，用该 override 进行最小规模 testnet 开仓/核对/平仓测试；主网仍需另行设计和明确确认。
