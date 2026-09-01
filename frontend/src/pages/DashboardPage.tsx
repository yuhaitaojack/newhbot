import { useEffect, useState } from "react";
import { api, type Status } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";

export function DashboardPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [message, setMessage] = useState("");

  async function refresh() {
    setStatus(await api<Status>("/api/status"));
  }

  async function command(path: string) {
    const result = await api<Record<string, unknown>>(path, { method: "POST" });
    setMessage(JSON.stringify(result));
    await refresh();
  }

  useEffect(() => {
    void refresh();
    const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${wsProtocol}://${window.location.host}/ws`);
    socket.onmessage = () => {
      void refresh();
    };
    socket.onclose = () => {
      void refresh();
    };
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => {
      socket.close();
      window.clearInterval(timer);
    };
  }, []);

  if (!status) {
    return <p>Loading…</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => void command("/api/trading/start")}>启动</Button>
        <Button variant="secondary" onClick={() => void command("/api/trading/stop")}>
          停止
        </Button>
        <Button variant="outline" onClick={() => void command("/api/trading/close-and-stop")}>
          平仓并停止
        </Button>
        <Button variant="outline" onClick={() => void command("/api/trading/close-and-continue")}>
          平仓并继续
        </Button>
        <Button variant="danger" onClick={() => void command("/api/trading/emergency-stop")}>
          紧急停止
        </Button>
      </div>
      {message ? <p className="text-xs text-zinc-500">{message}</p> : null}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardTitle>System Status</CardTitle>
          <p>{status.system_state}</p>
          <p className="text-xs text-zinc-500">trading_enabled={String(status.trading_enabled)}</p>
          <p className="text-xs text-zinc-500">estop={String(status.estop)}</p>
        </Card>
        <Card>
          <CardTitle>Strategy Status</CardTitle>
          <p>{String(status.settings.active_strategy)}</p>
          <p className="text-xs text-zinc-500">version {String(status.settings.active_strategy_version)}</p>
        </Card>
        <Card>
          <CardTitle>Balance</CardTitle>
          <p>equity {status.balance.equity}</p>
          <p className="text-xs text-zinc-500">available {status.balance.available}</p>
        </Card>
        <Card>
          <CardTitle>Position</CardTitle>
          <p>
            {status.position.side} {status.position.size} {status.position.symbol}
          </p>
          <p className="text-xs text-zinc-500">mirror source: {status.position.source}</p>
        </Card>
        <Card>
          <CardTitle>PnL</CardTitle>
          <p>{status.position.unrealized_pnl}</p>
        </Card>
        <Card>
          <CardTitle>Last Signal</CardTitle>
          <p>{status.last_signal ?? "—"}</p>
          <p className="text-xs text-zinc-500">{status.last_signal_reason}</p>
        </Card>
        <Card>
          <CardTitle>Last Order</CardTitle>
          <p>{status.last_order ? `${status.last_order.side} ${status.last_order.status}` : "—"}</p>
          <p className="text-xs text-zinc-500">{status.last_order?.cloid}</p>
        </Card>
        <Card>
          <CardTitle>Last Fill</CardTitle>
          <p>
            {status.last_fill ? `${status.last_fill.price} x ${status.last_fill.quantity}` : "—"}
          </p>
        </Card>
      </div>
    </div>
  );
}
