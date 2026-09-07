# Phase 116 Report

## 目标

修复策略管理页面多个策略激活按钮都只显示“激活”导致的可用性和浏览器/辅助技术识别问题，并完成最小前端回归。

## 问题与修复

策略列表中的非当前策略按钮原来都使用相同的文案“激活”，无法可靠区分目标。仅修改按钮显示文本并增加 `aria-label`，现在按钮包含策略名称和版本，例如 `激活 custom_hold v1.0.0`；激活逻辑、确认框和 API 没有改变。

## 验证结果

- `npm run build`：TypeScript 检查和 Vite production build 成功。
- 前端 Docker 镜像重建并重新部署成功。
- 浏览器 Dashboard → 策略管理页面加载正常。
- 未选文件时上传按钮仍为 disabled。
- 激活按钮在可访问性树中分别显示完整目标：`custom_hold v1.0.0`、`example_hold v1`。
- 当前激活策略仍为 `ema5break v1`；没有切换策略、没有启动交易、没有产生订单。

## 最终状态

系统保持 `STOPPED`、交易开关关闭、紧急停止未锁定、持仓 `FLAT/0`，Worker `READY/LIVE`。

## 安全边界

本阶段只修改前端按钮可识别性，没有修改策略逻辑、Trading Controller、执行路径或交易配置。
