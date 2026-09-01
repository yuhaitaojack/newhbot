# 策略上传安全

用户上传 `strategy.py` + `manifest.yaml`。这是任意代码执行面。

## 1. 威胁

任意文件读取、路径穿越、联网、os.system、import hummingbot/connector、死循环、崩溃、在策略里直接下单。

## 2. 是否独立进程？

**是。** 策略必须在独立进程，理由：

- 崩溃不影响 Trading Controller
- 可杀死循环
- 可用 OS 级丢掉网络（Linux `network` namespace / `AF_UNIX` 仅 stdin-stdout JSON）

## 3. 是否 Docker sandbox？

**v1 不给每个策略单独一个 Docker。** 完全 sandbox（每 tick 起容器）延迟大，不适合持续跑。策略已在 app 容器内时，再套一层 Docker 需要 docker.sock——已否决。

适合本项目的安全等级：**「受限子进程 + 导入白名单 + 无网络 + 超时」**，不是云上多租户隔离。

这是个人单用户系统：攻击者通常就是能登录这台机器的人。目标是防止策略文件**失误**或来路不明脚本碰到密钥和下单通道。

## 4. v1 规则

- 文件落在 `strategies/versions/<sha256>/`，拒绝 `..`。
- 只允许 `.py` 与 `manifest.yaml`。
- Runtime 用单独 Python（3.11），`PYTHONPATH` 不含 execution/密钥。
- 禁止模块：`os.system`、`subprocess`、`socket`、`ctypes`、`hummingbot`、任何 http 库。可用 AST 预扫 + 受限 builtins。
- IPC：stdin/stdout JSON。输入：OHLCV/持仓只读快照/参数。输出：一个 `{signal, reason}`。
- CPU 时间与 wall clock 超时；超限杀进程，信号视为 HOLD，记审计。
- 策略 **看不到** cloid、密钥、Worker RPC。
- 同时只启用一个版本。
- 参数：`manifest.yaml` 声明项；UI 开关关闭 → 用 manifest/策略默认；打开 → DB 用户值。策略不得自己读 DB。

## 5. 性能

子进程常驻，每根 K 线或每 N 秒发一次快照，对非 HFT 足够。不要每 tick 冷启动解释器。

PHASE 2 可做：用最简策略证明 IPC 延迟。不在本阶段实现。
