import { useEffect, useState } from "react";
import { api, errorMessage, type Status } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";

function formatCandleTimestamp(timestamp?: number | null): string {
  if (!timestamp) return "—";
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function formatDecimal(value: string | number | null | undefined): string {
  if (value == null) return "—";
  const text = String(value);
  return /^-?0(?:\.0*)?(?:E[+-]?\d+)?$/i.test(text) ? "0" : text;
}

function formatCommandResult(result: Record<string, unknown>, path?: string): { ok: boolean; text: string } {
  if (result.ok === false) {
    return { ok: false, text: `失败：${String(result.reason ?? JSON.stringify(result))}` };
  }
  if (path === "/api/trading/clear-estop" && result.ok === true) {
    return { ok: true, text: "已解除紧急停止，但系统仍保持停止" };
  }
  if (result.ok === true) {
    const extra = result.reason ? `（${String(result.reason)}）` : result.state ? ` state=${String(result.state)}` : "";
    return { ok: true, text: `成功${extra}` };
  }
  return { ok: true, text: `成功：${JSON.stringify(result)}` };
}

export function DashboardPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [loadError, setLoadError] = useState("");
  const [message, setMessage] = useState("");
  const [messageOk, setMessageOk] = useState(true);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      setStatus(await api<Status>("/api/status"));
      setLoadError("");
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }

  async function command(path: string) {
    if (busy) {
      return;
    }
    if (path === "/api/trading/clear-estop") {
      const confirmed = window.confirm(
        "确认仓位为 FLAT、无挂单、无未确认订单后，解除紧急停止？\n系统将保持停止，不会自动启动交易。",
      );
      if (!confirmed) {
        return;
      }
    }
    setBusy(true);
    setMessage("");
    try {
      const result = await api<Record<string, unknown>>(path, { method: "POST" });
      const formatted = formatCommandResult(result, path);
      setMessageOk(formatted.ok);
      setMessage(formatted.text);
      await refresh();
    } catch (err) {
      setMessageOk(false);
      setMessage(`失败：${errorMessage(err)}`);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void refresh();
    const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
    let socket: WebSocket | null = null;
    let reconnectTimer: number | undefined;
    let reconnectDelay = 1000;
    let disposed = false;

    function connect() {
      if (disposed) return;
      socket = new WebSocket(`${wsProtocol}://${window.location.host}/ws`);
      socket.onopen = () => {
        reconnectDelay = 1000;
      };
      socket.onmessage = () => {
        void refresh();
      };
      socket.onerror = () => {
        /* onclose schedules a bounded reconnect; polling remains the fallback */
      };
      socket.onclose = () => {
        socket = null;
        void refresh();
        if (!disposed) {
          reconnectTimer = window.setTimeout(connect, reconnectDelay);
          reconnectDelay = Math.min(reconnectDelay * 2, 10000);
        }
      };
    }

    connect();
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => {
      disposed = true;
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      socket?.close();
      window.clearInterval(timer);
    };
  }, []);

  if (!status && loadError) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-red-400">无法加载状态：{loadError}</p>
        <Button onClick={() => void refresh()}>重试</Button>
      </div>
    );
  }

  if (!status) {
    return <p>Loading…</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy} onClick={() => void command("/api/trading/start")}>
          启动交易
        </Button>
        <Button disabled={busy} variant="secondary" onClick={() => void command("/api/trading/stop")}>
          停止交易
        </Button>
        <Button disabled={busy} variant="outline" onClick={() => void command("/api/trading/close-and-stop")}>
          平仓并停止
        </Button>
        <Button disabled={busy} variant="outline" onClick={() => void command("/api/trading/close-and-continue")}>
          平仓后继续
        </Button>
        <Button disabled={busy} variant="danger" onClick={() => void command("/api/trading/emergency-stop")}>
          紧急停止
        </Button>
        {status.estop ? (
          <Button disabled={busy} variant="secondary" onClick={() => void command("/api/trading/clear-estop")}>
            解除紧急停止
          </Button>
        ) : null}
      </div>
      {busy ? <p className="text-xs text-zinc-500">执行中…</p> : null}
      {message ? <p className={`text-sm ${messageOk ? "text-emerald-400" : "text-red-400"}`}>{message}</p> : null}
      {loadError ? <p className="text-xs text-red-400">状态刷新失败：{loadError}</p> : null}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardTitle>系统状态</CardTitle>
          <p>{status.system_state}</p>
          <p className="text-xs text-zinc-500">交易开关={status.trading_enabled ? "已开启" : "已停止"}</p>
          <p className="text-xs text-zinc-500">紧急停止={status.estop ? "已锁定" : "未锁定"}</p>
        </Card>
        <Card>
          <CardTitle>策略状态</CardTitle>
          <p>{String(status.settings.active_strategy)}</p>
          <p className="text-xs text-zinc-500">version {String(status.settings.active_strategy_version)}</p>
        </Card>
        <Card>
          <CardTitle>账户资金</CardTitle>
          <p>账户权益 {formatDecimal(status.balance.equity)}</p>
          <p className="text-xs text-zinc-500">可用保证金 {formatDecimal(status.balance.available)}</p>
        </Card>
        <Card>
          <CardTitle>当前持仓</CardTitle>
          <p>
            {status.position.side} {formatDecimal(status.position.size)} {status.position.symbol}
          </p>
          <p className="text-xs text-zinc-500">数据来源：{status.position.source}</p>
        </Card>
        <Card>
          <CardTitle>执行 Worker</CardTitle>
          <p>{status.worker_state ?? "—"}</p>
          <p className="text-xs text-zinc-500">
            就绪={status.worker_ready ? "是" : "否"} · 同步={status.sync_status ?? "—"}
          </p>
          {status.hyperliquid_domain ? (
            <p className="text-xs text-zinc-500">域：{status.hyperliquid_domain}</p>
          ) : null}
        </Card>
        <Card>
          <CardTitle>策略循环</CardTitle>
          <p>{status.strategy_loop_running ? "运行中" : "已停止"}</p>
          <p className="text-xs text-zinc-500">
            最新 K 线={formatCandleTimestamp(status.strategy_loop_last_candle_timestamp)}
          </p>
          {status.strategy_loop_last_error ? (
            <p className="text-xs text-red-400">{status.strategy_loop_last_error}</p>
          ) : null}
        </Card>
        <Card>
          <CardTitle>未实现盈亏</CardTitle>
          <p>{formatDecimal(status.position.unrealized_pnl)}</p>
        </Card>
        <Card>
          <CardTitle>最近信号</CardTitle>
          <p>{status.last_signal ?? "—"}</p>
          <p className="text-xs text-zinc-500">{status.last_signal_reason}</p>
        </Card>
        <Card>
          <CardTitle>最近订单</CardTitle>
          <p>{status.last_order ? `${status.last_order.side} ${status.last_order.status}` : "—"}</p>
          <p className="text-xs text-zinc-500">{status.last_order?.cloid}</p>
        </Card>
        <Card>
          <CardTitle>最近成交</CardTitle>
          <p>
            {status.last_fill ? `${status.last_fill.price} x ${status.last_fill.quantity}` : "—"}
          </p>
        </Card>
      </div>
    </div>
  );
}
