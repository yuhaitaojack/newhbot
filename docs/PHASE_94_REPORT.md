# Phase 94 Report

## 目标

修复控制面 token 被注入前端静态 JavaScript 的安全问题。

## 实施

- 移除 Frontend Dockerfile 的 `VITE_CONTROL_API_TOKEN` build arg/ENV。
- 移除浏览器端 `Authorization` token 逻辑。
- 改为 Nginx 模板在容器启动时从 `CONTROL_API_TOKEN` 运行时环境向 `/api/` 和 `/ws` 上游注入 Bearer header。
- 默认 Mock Compose 提供空 token；live-readonly override 提供运行时 token，不再提供 build args。
- 限制 Nginx envsubst 只替换 `CONTROL_API_TOKEN`，保持 `$http_upgrade` 等 Nginx 变量不变。

## 验证

- Frontend `npm run build` 通过。
- 构建产物搜索不到 `VITE_CONTROL_API_TOKEN` 或 `CONTROL_API_TOKEN`。
- 默认 Frontend 容器稳定运行，Nginx 配置成功生成；`/api/health` 通过。
- live-readonly Compose 配置审计确认 token 位于 Frontend runtime environment，不在 build args 中。
- 浏览器 Dashboard 与策略页通过同源 Nginx 代理加载成功，控制按钮、状态和策略参数显示正常。
- 正式本地栈仍为 Mock、`execution_enabled=false`、STOPPED、FLAT/0、Worker READY/LIVE。

## 安全边界

未连接 Hyperliquid 主网，未读取真实密钥，未发送订单。

