# Phase 121 Report

## 目标

补齐 Hyperliquid 主网与 testnet 的显式域隔离，确保真实执行验证可以先在 testnet 进行，而不是因官方连接器默认值而意外使用主网。

## 实现

- 新增 `HYPERLIQUID_DOMAIN` 配置，仅允许官方域名 `hyperliquid_perpetual_testnet` 或 `hyperliquid_perpetual`。
- 默认域为 `hyperliquid_perpetual_testnet`；主网必须显式设置 `HYPERLIQUID_DOMAIN=hyperliquid_perpetual`。
- 工厂将域名显式传入官方 Hummingbot v2.16.0 Hyperliquid 连接器，而不是依赖连接器默认值。
- 示例 Compose 与 `.env.example` 明确标示 testnet 默认及主网显式覆盖要求；真实密钥仍只能从外部环境或 Docker secret 注入。

## 验证

- 新增域配置测试，连同执行路径回归共 `51 passed`。
- Worker 全量测试：`101 passed, 1 skipped`。
- 官方 Hummingbot v2.16.0 镜像直接实例化验证：testnet/mainnet 两个 domain 均正确保留。
- Docker Compose Worker 已重建并启动。
- 运行态：`STOPPED`、交易开关关闭、紧急停止关闭、Worker `READY`、同步 `LIVE`、持仓 `FLAT/0`。

## 安全边界

本 Phase 未连接任何 Hyperliquid 域、未读取真实账户、未发送真实订单。默认 Compose 仍为 Mock；主网仍需当前会话明确确认后才可进行任何私有 API 或订单操作。

