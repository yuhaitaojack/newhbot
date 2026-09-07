import { useEffect, useState } from "react";
import { api, errorMessage } from "@/api";
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
  trading_enabled: boolean;
  estop: boolean;
  system_state: string;
};

export function SettingsPage() {
  const [form, setForm] = useState<Settings | null>(null);
  const [loadError, setLoadError] = useState("");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setForm(await api<Settings>("/api/settings"));
      setLoadError("");
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  if (!form && loadError) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-red-400">无法加载设置：{loadError}</p>
        <Button onClick={() => void load()}>重试</Button>
      </div>
    );
  }

  if (!form) return <p>Loading…</p>;

  const editable = form.system_state === "STOPPED" && !form.trading_enabled;

  async function save() {
    if (!form || busy) return;
    setBusy(true);
    setSaved("");
    try {
      const payload = {
        ...form,
        leverage: Number(form.leverage),
        limit_timeout: Number(form.limit_timeout),
        position_percentage: String(form.position_percentage),
        slippage: String(form.slippage),
      };
      const next = await api<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
      setForm(next);
      setSaved("已保存");
    } catch (err) {
      setSaved(`保存失败：${errorMessage(err)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="max-w-xl space-y-3">
      <CardTitle>交易设置</CardTitle>
      {(
        [
          ["交易币种", "trading_pair", "实际交易的 Hyperliquid 永续合约交易对。"],
          ["杠杆倍数", "leverage", "Controller 在开仓前校验的目标杠杆；策略本身不能修改杠杆。"],
          ["仓位比例（%）", "position_percentage", "按账户权益计算开仓名义金额；还必须满足交易所最小订单金额。"],
          ["订单类型", "order_type", "开仓订单使用的订单类型，例如 MARKET。"],
          ["限价超时（秒）", "limit_timeout", "限价单等待成交的最长时间，超时后由安全流程处理。"],
          ["滑点容忍度", "slippage", "市价/IOC 价格相对中间价允许的最大滑点。"],
        ] as const
      ).map(([label, key, help]) => (
        <label key={key} className="block text-sm">
          {label}
          <input
            className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1"
            value={form[key] == null ? "" : String(form[key])}
            disabled={!editable || busy}
            onChange={(event) => setForm({ ...form, [key]: event.target.value })}
          />
        </label>
      ))}
      <p className="text-xs text-zinc-500">当前策略：{form.active_strategy || "无"} · 版本：{form.active_strategy_version || "无"}（请在策略管理页面激活）</p>
      {!editable ? <p className="text-xs text-amber-300">系统当前为 {form.system_state}，交易设置仅可在 STOPPED 且交易开关关闭时修改。</p> : null}
      <Button disabled={busy || !editable} onClick={() => void save()}>
        保存设置
      </Button>
      <span className={`ml-2 text-xs ${saved.startsWith("保存失败") ? "text-red-400" : "text-zinc-500"}`}>{saved}</span>
    </Card>
  );
}
