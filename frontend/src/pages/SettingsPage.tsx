import { useEffect, useState } from "react";
import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";

type Settings = {
  trading_pair: string;
  leverage: number;
  position_percentage: string;
  order_type: string;
  limit_timeout: number;
  slippage: string;
  active_strategy: string | null;
  active_strategy_version: string | null;
};

export function SettingsPage() {
  const [form, setForm] = useState<Settings | null>(null);
  const [saved, setSaved] = useState("");

  useEffect(() => {
    void api<Settings>("/api/settings").then(setForm);
  }, []);

  if (!form) return <p>Loading…</p>;

  async function save() {
    if (!form) return;
    const payload = {
      ...form,
      leverage: Number(form.leverage),
      limit_timeout: Number(form.limit_timeout),
      position_percentage: String(form.position_percentage),
      slippage: String(form.slippage),
    };
    const next = await api<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
    setForm(next);
    setSaved("saved");
  }

  return (
    <Card className="max-w-xl space-y-3">
      <CardTitle>Settings (SQLite)</CardTitle>
      {(
        [
          ["trading_pair", "trading_pair"],
          ["leverage", "leverage"],
          ["position_percentage", "position_percentage"],
          ["order_type", "order_type"],
          ["limit_timeout", "limit_timeout"],
          ["slippage", "slippage"],
          ["active_strategy", "active_strategy"],
          ["active_strategy_version", "active_strategy_version"],
        ] as const
      ).map(([label, key]) => (
        <label key={key} className="block text-sm">
          {label}
          <input
            className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1"
            value={form[key] == null ? "" : String(form[key])}
            onChange={(event) => setForm({ ...form, [key]: event.target.value })}
          />
        </label>
      ))}
      <Button onClick={() => void save()}>Save</Button>
      <span className="ml-2 text-xs text-zinc-500">{saved}</span>
    </Card>
  );
}
