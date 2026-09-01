import { useEffect, useState } from "react";
import { api } from "@/api";
import { Card, CardTitle } from "@/components/ui/card";

export function StrategyPage() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    void api<Record<string, unknown>>("/api/strategy").then(setData);
  }, []);
  if (!data) return <p>Loading…</p>;
  return (
    <Card>
      <CardTitle>Strategy</CardTitle>
      <pre className="overflow-auto text-xs">{JSON.stringify(data, null, 2)}</pre>
    </Card>
  );
}

export function JsonListPage({ path, title }: { path: string; title: string }) {
  const [data, setData] = useState<unknown>(null);
  useEffect(() => {
    void api(path).then(setData);
  }, [path]);
  if (!data) return <p>Loading…</p>;
  return (
    <Card>
      <CardTitle>{title}</CardTitle>
      <pre className="overflow-auto text-xs">{JSON.stringify(data, null, 2)}</pre>
    </Card>
  );
}
