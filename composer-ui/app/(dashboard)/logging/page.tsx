"use client";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { listLogs } from "@/lib/api/logs";
import type { LogEntry } from "@/lib/types";

// Live tail of RedisLogger's own log stream (scarlets/utils/RedisLogger.py)
// - every RedisLogger call throughout the scarlets package and
// scarlet-agentic-harness's head/worker dispatch writes here, with a
// 10-minute TTL. Deliberately not durable history - see routers/logs.py's
// docstring for why that's a design choice, not a gap to fill later with
// more polling. 5s refresh (faster than Scarlets/Agents' 15s) since a log
// entry is only visible for ~10 minutes total, and the whole point of a
// live tail is seeing it soon after it happens.

const LEVEL_ORDER = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"];

function LevelBadge({ level }: { level: string }) {
  const upper = level.toUpperCase();
  if (upper === "CRITICAL" || upper === "ERROR") {
    return <Badge variant="destructive">{upper}</Badge>;
  }
  if (upper === "WARNING") {
    return <Badge className="border-transparent bg-yellow-100 text-yellow-800 hover:bg-yellow-100">{upper}</Badge>;
  }
  if (upper === "DEBUG") {
    return <Badge variant="outline">{upper}</Badge>;
  }
  return <Badge variant="secondary">{upper}</Badge>;
}

function formatTime(unixSeconds: number) {
  return new Date(unixSeconds * 1000).toLocaleString(undefined, {
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function LoggingPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["logs"],
    queryFn: listLogs,
    refetchInterval: 5_000,
  });

  const [levelFilter, setLevelFilter] = useState("All");
  const [appFilter, setAppFilter] = useState("All");
  const [nodeFilter, setNodeFilter] = useState("All");

  const logs: LogEntry[] = useMemo(
    () => (data && !data.error ? data.response.logs : []),
    [data]
  );

  const { appOptions, nodeOptions } = useMemo(() => {
    const apps = new Set<string>();
    const nodes = new Set<string>();
    for (const log of logs) {
      if (log.app) apps.add(log.app);
      if (log.node) nodes.add(log.node);
    }
    return { appOptions: Array.from(apps).sort(), nodeOptions: Array.from(nodes).sort() };
  }, [logs]);

  // All three filters combine with AND - the old Streamlit page combined
  // app/node filters with OR, so picking both showed anything matching
  // *either* rather than both. Fixed here.
  const filtered = logs.filter(
    (log) =>
      (levelFilter === "All" || log.level.toUpperCase() === levelFilter) &&
      (appFilter === "All" || log.app === appFilter) &&
      (nodeFilter === "All" || log.node === nodeFilter)
  );

  const selectClass =
    "h-9 rounded-md border border-input bg-transparent px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Logging</h1>
        <span className="text-xs text-gray-400">
          Live tail - entries expire after ~10 minutes, not a durable log store.
        </span>
      </div>

      <div className="flex flex-wrap gap-3">
        <select value={levelFilter} onChange={(e) => setLevelFilter(e.target.value)} className={selectClass}>
          <option value="All">All levels</option>
          {LEVEL_ORDER.map((lvl) => (
            <option key={lvl} value={lvl}>{lvl}</option>
          ))}
        </select>
        <select value={appFilter} onChange={(e) => setAppFilter(e.target.value)} className={selectClass}>
          <option value="All">All apps</option>
          {appOptions.map((app) => (
            <option key={app} value={app}>{app}</option>
          ))}
        </select>
        <select value={nodeFilter} onChange={(e) => setNodeFilter(e.target.value)} className={selectClass}>
          <option value="All">All nodes</option>
          {nodeOptions.map((node) => (
            <option key={node} value={node}>{node}</option>
          ))}
        </select>
        <span className="flex items-center text-xs text-gray-400">
          {filtered.length} of {logs.length} entries
        </span>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : filtered.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-gray-400">
            No log entries match the current filters.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="divide-y max-h-[70vh] overflow-y-auto">
              {filtered.map((log) => (
                <div key={log.id} className="flex items-start gap-3 px-4 py-2.5 text-sm">
                  <span className="w-40 shrink-0 font-mono text-xs text-gray-400">{formatTime(log.time)}</span>
                  <span className="w-24 shrink-0"><LevelBadge level={log.level} /></span>
                  <span className="w-32 shrink-0 truncate font-mono text-xs text-gray-500" title={log.app}>{log.app}</span>
                  <span className="w-28 shrink-0 truncate font-mono text-xs text-gray-500" title={log.node}>{log.node}</span>
                  <span className="flex-1 break-words">{log.msg}</span>
                  {log.filename && (
                    <span className="w-40 shrink-0 truncate text-right font-mono text-xs text-gray-400" title={`${log.filename}:${log.line}`}>
                      {log.filename.split("/").pop()}:{log.line}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
