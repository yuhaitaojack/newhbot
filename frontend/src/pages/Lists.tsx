import { useEffect, useState } from "react";
import { api, errorMessage, type Status } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";

export function StrategyPage() {
  const [data, setData] = useState<StrategyData | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [strategyFile, setStrategyFile] = useState<File | null>(null);
  const [manifestFile, setManifestFile] = useState<File | null>(null);
  const [parameterBusy, setParameterBusy] = useState<number | null>(null);
  const [controlState, setControlState] = useState<Pick<Status, "system_state" | "trading_enabled"> | null>(null);

  async function load() {
    try {
      const [strategy, status] = await Promise.all([
        api<StrategyData>("/api/strategy"),
        api<Status>("/api/status"),
      ]);
      setData(strategy);
      setControlState({ system_state: status.system_state, trading_enabled: status.trading_enabled });
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function upload() {
    if (!strategyFile || !manifestFile || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const form = new FormData();
      form.append("strategy.py", strategyFile, "strategy.py");
      form.append("manifest.yaml", manifestFile, "manifest.yaml");
      const result = await api<{ name: string; version: string; activated: boolean }>("/api/strategy/upload", {
        method: "POST",
        body: form,
      });
      setMessage(`已上传 ${result.name} ${result.version}，请在下方激活`);
      setStrategyFile(null);
      setManifestFile(null);
      await load();
    } catch (err) {
      setMessage(`上传失败：${errorMessage(err)}`);
    } finally {
      setBusy(false);
    }
  }

  async function activate(fileHash: string, name: string, version: string) {
    if (!editable || busy || !window.confirm(`激活 ${name} ${version}？系统必须处于 STOPPED 且无持仓。`)) return;
    setBusy(true);
    setMessage("");
    try {
      await api("/api/strategy/activate", {
        method: "POST",
        body: JSON.stringify({ file_hash: fileHash }),
      });
      setMessage(`已激活 ${name} ${version}；系统保持停止状态`);
      await load();
    } catch (err) {
      setMessage(`激活失败：${errorMessage(err)}`);
    } finally {
      setBusy(false);
    }
  }

  async function updateParameter(parameter: StrategyParameter, patch: { enabled?: boolean; current_value?: string }) {
    if (!editable || parameterBusy !== null) return;
    setParameterBusy(parameter.id);
    setMessage("");
    try {
      await api(`/api/strategy/parameters/${parameter.id}`, { method: "PUT", body: JSON.stringify(patch) });
      setMessage(`参数 ${parameter.name} 已保存`);
      await load();
    } catch (err) {
      setMessage(`参数保存失败：${errorMessage(err)}`);
    } finally {
      setParameterBusy(null);
    }
  }

  if (error && !data) {
    return <div className="space-y-3"><p className="text-sm text-red-400">无法加载策略：{error}</p><Button onClick={() => void load()}>重试</Button></div>;
  }
  if (!data) return <p>Loading…</p>;
  const editable = controlState?.system_state === "STOPPED" && !controlState.trading_enabled;
  return (
    <div className="max-w-3xl space-y-4">
      <Card className="space-y-3">
        <CardTitle>策略上传</CardTitle>
        <p className="text-xs text-zinc-400">仅支持 strategy.py + manifest.yaml。上传不会自动激活或启动。</p>
        <label className="block text-sm">策略源码 strategy.py<input className="mt-1 block text-xs" type="file" accept=".py" onChange={(e) => setStrategyFile(e.target.files?.[0] || null)} /></label>
        <label className="block text-sm">策略清单 manifest.yaml<input className="mt-1 block text-xs" type="file" accept=".yaml,.yml" onChange={(e) => setManifestFile(e.target.files?.[0] || null)} /></label>
        <Button disabled={busy || !strategyFile || !manifestFile} onClick={() => void upload()}>上传策略</Button>
        {message ? <p className={`text-xs ${message.includes("失败") ? "text-red-400" : "text-zinc-400"}`}>{message}</p> : null}
      </Card>
      <Card className="space-y-3">
        <CardTitle>当前策略参数</CardTitle>
        <p className="text-xs text-zinc-500">仅 STOPPED 状态可修改。关闭启用时使用策略默认值，启用后使用保存的当前值。</p>
        {!editable ? <p className="text-xs text-amber-300">系统当前为 {controlState?.system_state || "未知状态"}，策略参数和激活操作已锁定。</p> : null}
        {data.parameters.length === 0 ? <p className="text-sm text-zinc-500">当前策略没有可配置参数</p> : null}
        {data.parameters.map((parameter) => (
          <div key={parameter.id} className="space-y-2 rounded border border-zinc-800 p-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>{parameter.name} <span className="text-xs text-zinc-500">({parameter.type})</span></span>
              <span className="text-xs text-zinc-400">生效值：{parameter.effective_value}</span>
            </div>
            {parameter.description ? <p className="text-xs text-zinc-500">{parameter.description}</p> : null}
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={parameter.enabled} disabled={!editable || parameterBusy !== null} onChange={(event) => void updateParameter(parameter, { enabled: event.target.checked, current_value: parameter.current_value })} />
                启用自定义值
              </label>
              <input
                className="min-w-40 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs"
                value={parameter.current_value}
                disabled={!editable || parameterBusy !== null}
                onChange={(event) => setData({ ...data, parameters: data.parameters.map((item) => item.id === parameter.id ? { ...item, current_value: event.target.value } : item) })}
              />
              <Button disabled={!editable || parameterBusy !== null} onClick={() => void updateParameter(parameter, { current_value: parameter.current_value })}>保存值</Button>
              <span className="text-xs text-zinc-600">默认：{parameter.default_value}{parameter.min_value !== null ? `，范围 ${parameter.min_value}~${parameter.max_value}` : ""}</span>
            </div>
          </div>
        ))}
      </Card>
      <Card className="space-y-3">
        <CardTitle>已注册策略版本</CardTitle>
        <p className="text-sm">当前激活：<span className="text-emerald-400">{data.active_strategy || "无"} {data.active_strategy_version ? `v${data.active_strategy_version}` : ""}</span></p>
        <div className="space-y-2">
          {data.versions.map((version) => (
            <div key={`${version.id}-${version.file_hash}`} className="flex flex-wrap items-center justify-between gap-2 rounded border border-zinc-800 p-2 text-sm">
              <span>{version.name} <span className="text-zinc-500">v{version.version}</span></span>
              {data.active_strategy === version.name && data.active_strategy_version === version.version ? <span className="text-xs text-emerald-400">当前激活</span> : <Button disabled={!editable || busy} aria-label={`激活 ${version.name} v${version.version}`} onClick={() => void activate(version.file_hash, version.name, version.version)}>激活 {version.name} v{version.version}</Button>}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

type StrategyData = {
  active_strategy: string | null;
  active_strategy_version: string | null;
  versions: Array<{ id: number; name: string; version: string; file_hash: string }>;
  parameters: StrategyParameter[];
};

type StrategyParameter = {
  id: number;
  name: string;
  type: string;
  default_value: string;
  current_value: string;
  enabled: boolean;
  min_value: string | null;
  max_value: string | null;
  description: string | null;
  effective_value: string;
};

export function JsonListPage({ path, title }: { path: string; title: string }) {
  const [data, setData] = useState<unknown>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    setError("");
    void api<unknown>(path)
      .then((value) => {
        setData(value);
        setError("");
      })
      .catch((err: unknown) => {
        setError(errorMessage(err));
        setData(null);
      })
      .finally(() => {
        setLoading(false);
      });
  }

  useEffect(() => {
    load();
  }, [path]);

  if (loading && data === null) {
    return <p>Loading…</p>;
  }
  if (error && data === null) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-red-400">
          无法加载{title}：{error}
        </p>
        <Button onClick={load}>重试</Button>
      </div>
    );
  }
  const rows = Array.isArray(data) ? data.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object") : [];
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  return (
    <Card>
      <CardTitle>{title}</CardTitle>
      {error ? <p className="mb-2 text-xs text-red-400">刷新失败：{error}</p> : null}
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-zinc-500">暂无记录</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-max text-left text-xs">
            <thead className="border-b border-zinc-800 text-zinc-500">
              <tr>
                {columns.map((column) => <th key={column} className="whitespace-nowrap px-2 py-2 font-normal">{columnLabel(column)}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={String(row.id ?? rowIndex)} className="border-b border-zinc-900 align-top">
                  {columns.map((column) => <td key={column} className="max-w-80 whitespace-pre-wrap break-words px-2 py-2 text-zinc-300">{formatListValue(row[column])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function columnLabel(column: string): string {
  return column.replaceAll("_", " ");
}

function formatListValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
