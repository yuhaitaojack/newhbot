# 数据库与 Web 接口

## 1. SQLite vs PostgreSQL

| | SQLite | PostgreSQL |
| --- | --- | --- |
| 本项目负载 | 单用户、单策略、单币种、低频下单 | 官方 hummingbot-api 多 bot 分析才用 |
| 部署 | 文件 + volume | 又一个容器、密码、备份 |
| 崩溃恢复 | WAL + 备份文件 | 更强，但我们不需要其并发写 |
| Docker | 一个 volume | 官方还要把 5432 绑出来给 host 开发 |

**结论：SQLite 足够。不为「看起来专业」上 PostgreSQL。**

约束：

- 仅 **app** 进程写库（含 WAL）。execution 不连 SQLite。
- `journal_mode=WAL`，`synchronous=FULL`（交易系统，宁可慢）。
- 定期文件备份到同一 volume 的 `backup/`。
- 不把 SQLite 放在网络文件系统上。

## 2. 逻辑表（设计，不建库）

| 表 | 内容 |
| --- | --- |
| settings | 币种、杠杆、数量、running、estop、认证哈希等；单行或 key-value |
| strategy_versions | 上传文件哈希、路径、启用版本、上传时间 |
| strategy_parameters | 参数名、用户值、enabled 开关；enabled=false 则 Runtime 用策略默认 |
| signals | 时间、版本、信号、是否被 Guard 拒绝 |
| orders | intent_id、cloid、oid、side、reduce_only、status、qty |
| fills | oid、px、sz、fee、hash、tid |
| trades | 一次完整开到平的汇总（可选，可由 orders+fills 派生） |
| positions | 本地缓存快照，**每次以交易所覆盖** |
| account_snapshots | 权益、保证金 |
| system_events | 状态机迁移 |
| audit_logs | 谁在何时点了平仓/紧急停止/改参数 |

密钥不入库明文。

## 3. Web UI 页面

Dashboard / Strategy / Parameters / Settings / Orders / Fills / Trades / Positions / System Events / Audit Logs。

无 Charts/K 线。

实时：WebSocket 推送上述只读视图的脏标记或快照。命令走 REST（便于审计与幂等）。

## 4. UI WebSocket 重同步

1. 客户端保存 `last_event_id`。
2. 断线重连后 `GET /snapshot` 全量。
3. 再 `WS /ws?after=event_id`。
4. 若 event 间隙过大：丢增量，再用 snapshot。

不要只靠「推什么显示什么」。

## 5. 认证

v1：单用户密码（哈希存 SQLite）+ 会话 cookie 或 token；默认 loopback。远程访问：SSH 隧道或 Tailscale，而不是把端口打到 0.0.0.0。不接 MCP。
