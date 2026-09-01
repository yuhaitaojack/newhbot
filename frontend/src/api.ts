export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return (await response.json()) as T;
}

export type Status = {
  system_state: string;
  trading_enabled: boolean;
  estop: boolean;
  last_signal: string | null;
  last_signal_reason: string | null;
  settings: Record<string, unknown>;
  position: {
    symbol: string;
    side: string;
    size: string;
    unrealized_pnl: string;
    source: string;
  };
  last_order: { cloid: string; status: string; side: string } | null;
  last_fill: { cloid: string; price: string; quantity: string } | null;
  balance: { equity: string; available: string; margin_used: string };
  snapshot_event_id: number;
  worker_ready?: boolean;
  worker_state?: string | null;
  sync_status?: string | null;
};
