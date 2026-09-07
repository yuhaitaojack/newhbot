# newhbot 跨电脑部署与交接指南

本文是从 GitHub 克隆本项目后重新部署的主入口。项目是基于 Hummingbot Hyperliquid 永续连接器的单账户、单策略控制面，默认以 Mock 执行层启动；默认不会连接 Hyperliquid，也不会发送真实订单。

## 1. 项目组成

```text
frontend/          React + Vite + Nginx 控制面
backend/           FastAPI、SQLite、策略运行时、Trading Controller、Recovery
execution-worker/  独立执行层；复用 Hummingbot Hyperliquid 连接器
strategies/        可上传/激活的纯信号策略，当前包含 ema5break
docs/              架构、执行设计、阶段报告和本交接文档
docker-compose.yml 默认安全 Mock 栈
```

核心边界必须保持：策略只返回 `LONG`、`SHORT`、`CLOSE`、`HOLD`；所有下单、撤单、平仓和紧急停止都经过 Trading Controller；交易所状态优先于 SQLite；Recovery、未知订单、交易所查询失败时禁止开新仓；任意时刻最多一个实际持仓。

## 2. 目标电脑准备

推荐安装：

- Git 2.40 或更新版本。
- Docker Desktop（Windows 需要启用 WSL2；Linux 使用 Docker Engine + Compose v2；macOS 使用 Docker Desktop）。
- 至少约 10 GB 可用空间，首次构建需要下载官方 Hummingbot 镜像和 Node/Python 基础镜像。
- 能访问 Docker Hub、npm registry 和 Hyperliquid API（只有实时只读/交易模式才需要后者）。

不使用 Docker 时，才需要 Python 3.11+、Node.js 22+ 和 npm。跨电脑部署优先使用 Docker，避免 Windows 原生运行 Hummingbot 连接器。

Apple Silicon 会按 `docker-compose.yml` 中的 `linux/amd64` 构建执行 Worker，Docker Desktop 负责仿真；这比原生架构慢，但与锁定的 Hummingbot 镜像兼容。

## 3. 从 GitHub 获取代码

```bash
git clone <你的 GitHub 仓库 URL> newhbot
cd newhbot
git status
```

仓库不应包含以下内容：`.env` 实值、私钥/API secret、助记词、Hyperliquid credential 文件、SQLite 数据库、运行日志、Docker 本地状态。它们必须在目标电脑本地重新配置。

## 4. 默认 Mock 部署（推荐首次验证）

### Windows PowerShell

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/api/status | ConvertTo-Json -Depth 8
```

### macOS / Linux

```bash
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/api/status
```

打开 <http://127.0.0.1:8080>。首次启动会自动执行 Alembic migration，创建 `./data` 下的 SQLite 数据库，并启动 backend、execution-worker、frontend 三个服务。

首次状态应满足：

- `EXECUTION_MODE=mock`
- `EXECUTION_ENABLED=false`
- `trading_enabled=false`
- `strategy_loop_running=false`
- 没有真实交易所持仓和订单

Mock 模式的目标是验证 UI、策略信号、Controller、Recovery、数据库审计和停止/平仓门禁，不代表真实交易所延迟、滑点或成交行为。

常用生命周期命令：

```bash
docker compose logs -f backend
docker compose logs -f execution-worker
docker compose stop
docker compose start
docker compose down
```

不要让两套 backend 同时挂载同一个 `./data`；SQLite 是审计缓存，不是交易所真相源，但并发写入仍会造成锁冲突。

## 5. 本地测试

Docker 部署验证通过后，可在宿主机运行单元测试。两个子项目分别安装依赖并分别执行测试：

```bash
python -m venv .venv
# Windows PowerShell: .\\.venv\\Scripts\\Activate.ps1
# macOS/Linux:       source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e "backend[dev]"
python -m pip install -e "execution-worker[dev]"

python -m pytest backend/tests -q
python -m pytest execution-worker/tests -q
```

测试失败时先记录完整错误，不要通过删除测试、放宽断言或直接启用真实交易来绕过。

## 6. Hyperliquid 只读验证

只读验证需要账户地址和对应 API wallet secret，但仍不得打开执行权限。推荐使用仓库提供的脚本，在本地未跟踪文件中保存凭据，例如 Windows 的 `C:\\Users\\<用户>\\Desktop\\hyper.txt`。该文件不应复制到仓库。

```powershell
.\\scripts\\live_readonly_preflight.ps1 -CredentialFile 'C:\\Users\\<用户>\\Desktop\\hyper.txt'
```

脚本只把凭据传给一次性的 Worker 容器，输出认证、Worker 状态、持仓数量、挂单数量和余额是否可读，不打印私钥。默认域是 Hyperliquid testnet；确认域名、账户和输出无误后再继续任何写操作。

如果 Docker Hub 或 Hummingbot 镜像拉取失败，先处理网络、代理、Docker Hub 登录或磁盘空间；不要修改 Hummingbot 基础镜像版本来绕过问题。

## 7. Testnet 写入模式（必须单独确认）

仓库中的 `docker-compose.testnet-live.example.yml` 只允许明确的 testnet 写入配置，主网域名不会从该文件启用。真实凭据通过目标电脑的环境变量、Docker secret 或受保护的本地注入脚本提供：

```powershell
$env:HYPERLIQUID_DOMAIN = 'hyperliquid_perpetual_testnet'
$env:HYPERLIQUID_PERPETUAL_ADDRESS = '<testnet master address>'
$env:HYPERLIQUID_PERPETUAL_SECRET_KEY = '<testnet api-wallet secret>'
$env:CONTROL_API_TOKEN = '<long random control token>'

docker compose -f docker-compose.yml -f docker-compose.testnet-live.example.yml config
docker compose -f docker-compose.yml -f docker-compose.testnet-live.example.yml up -d --build
```

正式启用前逐项确认：

1. 地址是目标 testnet 主账户地址，secret 是与其匹配的 API wallet，不是主网密钥。
2. 账户、交易对、杠杆、仓位比例、最小名义金额和滑点都已复核。
3. 先做只读预检，确认交易所空仓、无挂单、Worker READY、WebSocket/LIVE 同步正常。
4. 通过 UI 或受保护 API 启动，不要直接调用 Worker 下单接口。
5. 运行期间只允许一个监控/策略循环；停止时先停策略循环和交易开关，再停止 Worker。

## 8. 主网边界

主网不是默认部署路径。主网需要在目标电脑上显式设置 `HYPERLIQUID_DOMAIN=hyperliquid_perpetual`、单独的主网 API wallet 和控制 token，并重新进行只读预检与人工确认。绝不能把主网密钥写入 `.env.example`、SQLite、日志、GitHub Issue 或 Git 历史。

## 9. 已知注意事项与历史问题

- 执行 Worker 使用固定的 Hummingbot `v2.16.0` 镜像；其官方镜像是 Linux 运行时，Windows 通过 Docker Desktop/WSL2 运行。
- `backend` 和 `execution-worker` 不能共享 SQLite；只有 backend 访问 `./data`，Worker 不访问本地数据库。
- `./data`、`./logs`、`backend/logs` 只用于本机运行，已被 Git 忽略；换电脑后历史交易记录不会随仓库迁移。
- Worker 停止、启动对账未完成或交易所连接不可用时，backend 显示 `RECOVERY`/`NOT_READY` 是安全门禁，不是允许开仓的状态。
- Hyperliquid 的交易所状态优先。若本地 SQLite 和交易所不一致，不能手动改数据库“纠正”；应让 Recovery 对账或执行明确的安全平仓流程。
- 不要同时启动旧的 phase 测试栈、正式 Compose 栈和第二个 Worker；这会导致端口、SQLite 或 Worker 心跳竞争。
- Hyperliquid 的“市价”由连接器用带滑点的 IOC 限价实现，不能按传统交易所原生市价的成交语义估计风险。
- 网络超时后的开仓不能随意换新 `cloid` 重发，避免重复开仓；应先查询订单、挂单和仓位，必要时进入 Recovery。
- 当前策略是信号型 `ema5break`，不是完整的 Hummingbot Strategy V2 Controller；策略不得直接调用交易所或下单函数。
- 最近一次实盘流程在用户要求下停止，完成计数为 LONG 2/5、SHORT 4/5；未完成的运行状态和数据库没有提交到 GitHub，重新部署后必须从只读预检开始。
- 某些执行 Worker 的真实连接器测试需要访问 `api.hyperliquid.xyz`；若目标机器 DNS、代理或防火墙不通，该测试会失败，但 Mock 测试不受影响，不能用修改测试来掩盖网络问题。

## 10. 重新部署完成检查表

```text
[ ] git clone 成功，git status 干净
[ ] .env 仅为本地文件，真实密钥未进入 Git
[ ] docker compose config --quiet 通过
[ ] 三个容器健康运行
[ ] /api/status 可访问且默认 execution_enabled=false
[ ] Web UI 可打开，策略循环默认未启动
[ ] backend/tests 和 execution-worker/tests 通过
[ ] 若做只读验证，确认 testnet/mainnet 域名与账户匹配
[ ] 若做写入测试，已单独确认交易对、仓位、杠杆、数量和停止流程
```

相关深入文档：

- `AGENTS.md`：不可违反的交易安全规则。
- `docs/ARCHITECTURE.md`：组件边界和状态流转。
- `docs/EXECUTION_DESIGN.md`：Hyperliquid 执行、幂等和精度设计。
- `docs/HUMMINGBOT_INTEGRATION.md`：为何只复用 Hummingbot 连接器。
- `docs/DEPLOYMENT.md`：Docker 拓扑和平台约束。
- `docs/PROJECT_HANDOVER_STATUS_REPORT.md`：阶段交接和历史验证记录。
- `docs/PHASE_145_REPORT.md`：最近的 Recovery/实时监控验证记录。
