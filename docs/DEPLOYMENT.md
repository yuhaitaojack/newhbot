# 部署与 Docker

Docker **不是因为流行才选**。比较后，生产环境仍推荐 Compose；理由是 Hummingbot 连接器官方不支持原生 Windows，且需要 Linux/ARM 镜像才能在 Apple Silicon 上跑。

## 1. 方案比较

| | 1. 全套官方 hummingbot-api Compose | 2. 原生 Python+Node 无 Docker | 3. 仅 HB 容器 + 本地 Backend | 4. 全部 Docker 单容器 | **5. Compose：app + execution（推荐）** |
| --- | --- | --- | --- | --- | --- |
| Windows | 需 Docker Desktop + WSL2 | HB 官方不支持 Win 原生 | Desktop+WSL2 | 同左 | 同左 |
| macOS Intel | 可 | conda 源码可，重 | 可 | 可 | 可 |
| macOS ARM | 官方 HB 镜像有 **linux/arm64**（version-2.16.0） | conda ARM 可用但本项目不走这条作为生产 | 可 | 可 | **可** |
| Linux x86_64 | 可 | 可 | 可 | 可 | 可 |
| Linux ARM64 | 镜像存在 | 源码视依赖 | 可 | 可 | **可** |
| 长时间运行 | restart 策略有，但组件太多 | systemd 自行拼 | Backend 不随 Docker 重启 | 单进程爆炸半径大 | `restart: unless-stopped` |
| 自动重启 | 有 | 要自己写 | 半套 | 有 | 有 |
| 数据持久化 | Postgres volume | 路径混乱 | SQLite 在主机 | 一个 volume | SQLite named volume 只挂 app |
| 日志 | json-file | 主机文件 | 分裂 | 混合 | 分容器 json-file + 轮转 |
| 升级 | 整栈 latest 易漂 | pip 地狱 | HB 镜像可钉 tag | 难单独升 connector | execution 钉 `version-2.16.0` |
| 故障恢复 | docker.sock 风险 | 主机杀进程 | Backend 死了 Worker 仍在 | 全死 | 分容器，符合 Recovery 设计 |
| 安全 | 官方警告勿暴露 8000；还挂 docker.sock | 密钥在用户环境 | 本机 API 需绑 loopback | 策略与密钥同容器 | 策略在 app，密钥在 execution |

不选 1：Postgres + EMQX + docker.sock 对单策略是负担和风险。  
不选 2：本机 PHASE 0 无 Docker、Python 3.14、Windows 非官方 HB 路径。  
不选 3 作为生产：Windows 重启后 Backend 不会自动起来，除非再装 Windows 服务；两套生命周期。开发期可用。  
不选 4：策略沙箱与密钥同命运。

## 2. 推荐拓扑

```
compose
  app:        我们的 API + 静态 UI + SQLite volume + 策略文件 volume
  execution:  Hummingbot connector worker；无 SQLite；只拿密钥 env
  volumes:    data/  logs/  strategies/
  ports:      127.0.0.1:8080  （UI/API）
              execution 不映射公网
```

网络：内部 bridge。app → execution 只走内部 RPC。

**不**挂载 `/var/run/docker.sock`。

## 3. 本机约束（来自 PHASE 0，仍有效）

- 当前 Windows 无 Docker Desktop，WSL 发行版未就绪。
- C: 仅约 22.8 GB 空闲；Docker 数据目录应放到 D/E/F。
- PHASE 2 开始前需要用户确认安装 Docker Desktop + WSL2 Ubuntu。

## 4. Apple Silicon

Docker Hub `hummingbot/hummingbot:version-2.16.0` 提供 linux/arm64（约 1.28 GB compressed）。**可以部署**，前提是我们的 app 镜像也提供 arm64 或用多阶段构建。PHASE 2 做镜像时验证，不在本阶段构建。
