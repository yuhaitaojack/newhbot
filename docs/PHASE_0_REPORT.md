# PHASE 0 报告：项目初始化与环境审查

**状态：** 完成并停止。未实现核心业务，未连接 Hyperliquid，未执行真实交易。  
**日期：** 2026-09-01  
**工作区：** `E:\yu_cursor_workspace\newhbot`

## 1. 本阶段做了什么

1. 检查当前目录、操作系统、CPU 架构与硬件余量。
2. 检查 Git、Python、Node、npm/pnpm、Docker、Docker Compose、WSL、uv。
3. 确认当前目录原先无项目文件；未删除任何已有文件。
4. 盘点 Cursor 当前可用的 MCP、Skills、Rules、Subagents，并判断对本项目的实际价值。
5. **未安装** 额外 Cursor 插件、未安装 pnpm、未安装 Docker Desktop（见第 8 节）。
6. 写入 `AGENTS.md`、`.cursor/rules/trading-safety.mdc`、`docs/PROJECT_REQUIREMENTS.md`。
7. 建立 Git 仓库并完成初始提交。
8. 停止。不进入 PHASE 1。

## 2. 机器与目录

| 项 | 结果 |
| --- | --- |
| 当前目录 | `E:\yu_cursor_workspace\newhbot` |
| PHASE 0 开始时内容 | 空目录（无已有项目、无 `.git`） |
| OS | Windows 10 企业版，10.0.19045（21H2/22H2 线），64-bit |
| CPU | Intel Core i5-9400F @ 2.90GHz，6 核 6 线程 |
| 架构 | AMD64（x86_64），`PROCESSOR_ARCHITECTURE=AMD64` |
| 内存 | 15.9 GB（满足 Hummingbot 文档“每实例 ≥ 4 GB”） |
| 磁盘 | C: 约 22.8 GB 空闲（偏紧）；D: 63.3 GB；E: 197.8 GB；F: 408.5 GB |
| 主机名 | DESKTOP-Q03O8GV |
| 用户 | Admin |

**结论：** 本机可作为 Windows 开发机。C: 空闲空间不足支撑 Docker 镜像默认装在系统盘；后续若安装 Docker，数据目录应放到 D/E/F。

## 3. 开发工具链

| 工具 | 状态 | 版本 / 路径 | 对本项目 |
| --- | --- | --- | --- |
| Git | 已安装 | 2.55.0.windows.3，`d:\Program Files\Git\cmd\git.exe` | 必要，已用于初始提交 |
| Git 用户身份 | 未配置 | 全局无 `user.name` / `user.email` | 初始提交使用一次性 `-c` 覆盖，**未改 git config** |
| Python（默认） | 已安装 | 3.14.5，`C:\Python314\python.exe` | 偏新；Hummingbot 源码/Cython 生态通常按 3.11/3.12 验证，**不要用 3.14 直接装 Hummingbot** |
| pip | 已安装 | 26.2.1（绑定 Python 3.14） | 仅服务 3.14 |
| venv | 可用 | 标准库 | 可用 |
| uv | 已安装 | 0.11.14 | 有用：本机已有其管理的 CPython 3.11.15 |
| Python 3.11 | 可用（uv） | 3.11.15 | 后续本地工具/测试的合理版本；执行层仍应以 Docker 内 Hummingbot 为准 |
| Conda / Anaconda | 未安装 | — | Hummingbot **源码安装**官方依赖 Conda；本项目规划用 Docker，不必现在装 |
| Poetry / pipx | 未安装 | — | 非必要 |
| Node.js | 已安装 | v24.18.0 x64，`D:\Program Files\nodejs\node.exe` | Web UI 足够 |
| npm | 已安装 | 12.0.2 | 采用 npm，不另装 pnpm |
| pnpm | 未安装 | — | **不安装**（npm 已满足） |
| make | 未安装 | — | 仅在跟上游 Hummingbot Makefile 时需要；Docker 方案可不依赖宿主机 make |
| Docker | **未安装** | PATH 与常见安装路径均无 | **后续 Phase 阻断项** |
| Docker Compose | **未安装** | `docker compose` 与 `docker-compose` 均无 | 同上 |
| Docker Desktop | **未安装** | 常见 `Program Files` 路径不存在 | 同上 |
| WSL | 功能已开，发行版未就绪 | `Microsoft-Windows-Subsystem-Linux=Enabled`，`VirtualMachinePlatform=Enabled`；`wsl --status` / `wsl -l` 提示需更新内核并从 Store 安装发行版 | Docker Desktop on Windows 通常需要可用的 WSL2 |
| Windows Containers 功能 | Disabled | — | 本项目用 Linux 容器，不需要开 Windows Containers |

**未连接网络交易所，未运行任何交易相关命令。**

## 4. 是否已有项目

PHASE 0 开始时：目录为空，不是 Git 仓库。

本阶段**新建**（未覆盖、未删除任何预先存在的文件）：

- `AGENTS.md`
- `README.md`
- `.gitignore`
- `.gitattributes`
- `.cursor/rules/trading-safety.mdc`
- `docs/PROJECT_REQUIREMENTS.md`
- `docs/PHASE_0_REPORT.md`

## 5. Cursor 能力盘点

### 5.1 MCP（当前会话）

| Namespace | 状态 | 对本项目 |
| --- | --- | --- |
| `cursor`（CreateGoal / UpdateGoal / GenerateImage） | 可用 | CreateGoal 仅在用户明确要求长周期目标时用。GenerateImage **不用**。 |
| `cursor-app-control` | ready | 工作区/对话控制。**不**把交易安全规则写入用户级 Personal Rules（应留在仓库 `AGENTS.md`）。 |
| `cursor-ide-browser` | ready | **后续 Web UI 联调与行为验证有用**。PHASE 0 无界面，未使用。 |
| `plugin-datadog-datadog` | error | 发现失败。本阶段无生产观测需求。**不修复、不安装、不启用。** |
| `plugin-figma-figma` | needsAuth | 无 Figma 设计稿。**不认证、不启用。** |

### 5.2 Skills（本机 Cursor）

可用但 **PHASE 0 实际用到的**：`create-rule`（项目规则格式）。

与本项目后续**可能有关、按需使用、现在不扩展**：

- Web UI 验证：用户规则已要求浏览器走查；配合 `cursor-ide-browser`。
- 代码审查：`review-security` / `review-bugbot`（仅当用户明确要求时启动对应 subagent）。
- 仓库托管：`origin` / `new-repo` / `share`（仅当用户要求远程仓库时）。

明确 **不要为这个项目启用或堆砌的**：

- Figma 全套 skill（无设计交付）。
- Datadog skill（MCP 已损坏且无观测栈）。
- Canvas / 图片生成（本阶段交付是安全基线文档，不是分析看板）。
- Automations / loop / hooks（交易系统禁止无人值守乱触发；后续若做 CI，再单独立项）。

### 5.3 Rules

| 来源 | 状态 | 处理 |
| --- | --- | --- |
| 用户级 Personal Rules（MCP `cursor_dialog` list） | 0 条 | 不向用户级写入交易规则 |
| 会话附带的用户偏好 | 有：Git 提交规范、PR 流程、Web UI 须浏览器验证 | 遵守；不复制进插件 |
| 项目规则 | PHASE 0 前不存在 | 已新增 alwaysApply：`.cursor/rules/trading-safety.mdc` |
| `AGENTS.md` | PHASE 0 前不存在 | 已写入完整硬性安全规则 |

### 5.4 Subagents（Cursor 内置）

| Subagent | 现在 | 后续 |
| --- | --- | --- |
| `explore` | 未需要（空仓库） | 代码变大后用于定向检索 |
| `generalPurpose` / `shell` | 环境检查已由主会话完成 | 按需 |
| `security-review` | 未跑（无业务代码） | 交易路径落地后、用户明确要求时使用 |
| `bugbot` | 未跑 | 仅当用户明确要求 |
| `ci-investigator` | 无 CI | 有 PR/CI 后再用 |
| `cursor-guide` | 未需要 | 问 Cursor 产品问题时用 |
| `best-of-n-runner` | 不需要 | 避免并行改交易核心 |

**未创建自定义 subagent。** 内置已够用，堆专用 agent 会稀释安全规则。

## 6. 哪些工具真正有助于本项目

**现在就该留下的：**

- Git + `.gitignore`（防密钥入库）
- `AGENTS.md` + 项目 alwaysApply rule（强制执行安全边界）
- npm / Node（未来 Web UI）
- uv + Python 3.11.15（未来本地测试，避免 3.14）
- 后续：`cursor-ide-browser`（UI 行为验证）
- 后续：`security-review`（交易路径审查）

**必须有、但本机缺失、留给下一阶段安装（需用户确认）：**

- Docker Desktop（含 Compose v2）
- 可用的 WSL2 内核与 Linux 发行版（Ubuntu）
- 可选：将 Docker 数据盘放到非 C: 盘

**明确不装：**

- pnpm（与 npm 重复）
- Conda（选 Docker 执行 Hummingbot 则非现在所需）
- Figma / Datadog 插件
- 其他 Cursor Marketplace 插件
- 自定义 subagent / hook / automation

## 7. 与 Hummingbot / Hyperliquid 相关的环境含义

公开文档（审查时查阅，**未调用交易所**）：

- Hummingbot 支持 Hyperliquid 永续：`hyperliquid_perpetual`，testnet 为 `hyperliquid_perpetual_testnet`。
- 永续持仓模式文档为 **One-way**，与“永远最多一个持仓”一致。
- Windows 官方路径：Docker Desktop + WSL2，或 WSL2 内源码 + Conda。
- 当前稳定发布说明指向 2.16.0（2026-07-29），含 Hyperliquid perp 价格量化修复。

因此：本项目的执行层应放进 Linux 容器，而不是在 Windows Python 3.14 上源码编译 Hummingbot。

## 8. 安装决策（只装必要工具）

| 候选 | 决策 | 理由 |
| --- | --- | --- |
| 项目 Git 仓库 | **已做** | 用户明确要求初始提交 |
| `AGENTS.md` / 需求文档 / 本报告 | **已做** | PHASE 0 交付物 |
| 项目 Cursor rule | **已做** | 让安全规则在每次会话生效；不是第三方插件 |
| pnpm | 不装 | npm 已在 |
| Docker Desktop | **本阶段不装** | 需管理员、WSL2 内核、可能重启；C: 空间紧；属于基础设施，应在用户确认的后续 Phase 安装 |
| WSL 发行版 | **本阶段不装** | 同上 |
| Conda | 不装 | 与 Docker 方案重复 |
| Figma / Datadog | 不装不认证 | 与当前需求无关；Datadog MCP 处于 error |
| 任何 Hyperliquid / Hummingbot 运行时 | **不装不连** | PHASE 0 禁止真实连接与交易 |

## 9. Git 初始提交

- 执行 `git init` 于 `E:\yu_cursor_workspace\newhbot`。
- 纳入上述新建文件。
- `.gitignore` 已排除 `.env`、密钥、SQLite、日志、`conf/connectors` 等。
- 提交说明见仓库 `git log`。因机器未配置 Git 身份，提交使用命令级 `git -c user.name` / `user.email`，**没有**执行 `git config` 写入。

## 10. 风险与下一 Phase 前置条件

下一 Phase 开始前建议由用户确认：

1. 安装 Docker Desktop，并把镜像/数据目录放到 D、E 或 F（C: 仅约 22.8 GB 空闲）。
2. 完成 WSL2 内核更新并安装 Ubuntu 发行版（功能开关已是 Enabled，但发行版未就绪）。
3. 本地开发 Python 固定 3.11 或 3.12（uv 已有 3.11.15），不要用 3.14 跑 Hummingbot。
4. 仍禁止主网；若做连通性，只能在用户明确批准后使用 testnet / mock。

**PHASE 0 不实现：** Trading Controller、策略运行时、Web UI、SQLite schema、Docker Compose、Hummingbot 集成。

## 11. 停止

PHASE 0 已完成。Agent 停止，等待用户指示 PHASE 1。
