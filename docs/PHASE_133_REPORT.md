# PHASE 133 REPORT

日期：2026-09-06

## 目标

修复 Hyperliquid testnet 配置下公共行情 helper 仍使用主网 REST URL 的域隔离缺口。

## 完成项

- 新增按 `HYPERLIQUID_DOMAIN` 选择 Hyperliquid `info` URL 的集中映射。
- Worker candles 使用配置域名；默认 testnet，显式 mainnet 才使用主网。
- instrument metadata helper 默认 testnet，并支持显式域名参数。
- 增加 testnet 与显式 mainnet URL 回归测试。

## 验证

- Worker：`108 passed, 1 skipped`。
- Backend：`156 passed, 1 warning`。
- Docker Compose Worker 镜像重建并启动成功。
- 浏览器点击测试：Dashboard 启动 `RUNNING`，停止 `STOPPED`；全程 `FLAT 0`。
- 当前 Compose：Mock 执行、`EXECUTION_ENABLED=false`、Worker `READY/LIVE`。
- 未连接 Hyperliquid 写接口，未发送真实订单。

## 当前边界

完整实盘写入仍需单独的逐次 testnet 确认和更高风险验证；主网默认关闭且不在本阶段执行。
