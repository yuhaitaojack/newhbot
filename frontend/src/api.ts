export function errorMessage(err: unknown): string {
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return String(err);
}

function formatHttpError(status: number, body: string): string {
  const trimmed = body.trim();
  if (!trimmed) {
    return `请求失败（${status}）`;
  }
  try {
    const parsed = JSON.parse(trimmed) as Record<string, unknown>;
    const detail = parsed.detail ?? parsed.reason ?? parsed.message;
    if (typeof detail === "string" && detail) {
      return `${status}: ${detail}`;
    }
  } catch {
    /* body is not JSON */
  }
  return `${status}: ${trimmed}`;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
    const headers = new Headers(init?.headers);
    if (!isFormData) headers.set("Content-Type", "application/json");
    response = await fetch(path, { ...init, headers });
  } catch (err) {
    throw new Error(`无法连接后端：${errorMessage(err)}`);
  }
  if (!response.ok) {
    throw new Error(formatHttpError(response.status, await response.text()));
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
  hyperliquid_domain?: string | null;
  strategy_loop_running?: boolean;
  strategy_loop_last_error?: string | null;
  strategy_loop_last_candle_timestamp?: number | null;
};
