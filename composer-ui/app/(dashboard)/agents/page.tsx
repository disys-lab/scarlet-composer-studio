"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getAgents } from "@/lib/api/agents";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/StatusPill";
import { Input } from "@/components/ui/input";
import type { Agent } from "@/lib/types";

// Replaces scarletcomposer/pages/Agents.py. Auto-refresh via React Query's
// refetchInterval (matches the old page's 15s cadence) instead of a
// manual sleep()+st.rerun() loop.
function ageLabel(ts: number | null) {
  if (!ts) return "unknown";
  const age = Date.now() / 1000 - ts;
  if (age < 60) return `${Math.floor(age)}s ago`;
  if (age < 3600) return `${Math.floor(age / 60)}m ago`;
  return `${Math.floor(age / 3600)}h ago`;
}

function AgentCard({ agent }: { agent: Agent }) {
  const [showRaw, setShowRaw] = useState(false);
  return (
    <Card>
      <CardContent className="p-4 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <StatusPill status={agent.health} />
            <span className="font-mono text-sm font-medium">{agent.agent_id}</span>
          </div>
          <button
            onClick={() => setShowRaw((v) => !v)}
            className="text-xs text-blue-600 hover:underline"
          >
            {showRaw ? "Hide" : "Raw JSON"}
          </button>
        </div>
        <p className="text-xs text-gray-500">
          Instance: <span className="font-mono">{agent.instance_id?.slice(0, 12) ?? "—"}…</span>
          {"  ·  "}Heartbeat: {ageLabel(agent.ts)}
        </p>
        {agent.capabilities.length > 0 && (
          <p className="text-sm">
            <span className="font-medium">Capabilities:</span>{" "}
            {agent.capabilities.map((c) => (
              <code key={c} className="mr-1 rounded bg-gray-100 px-1.5 py-0.5 text-xs">{c}</code>
            ))}
          </p>
        )}
        {agent.data_sources.length > 0 && (
          <p className="text-sm">
            <span className="font-medium">Data sources:</span>{" "}
            {agent.data_sources.map((d) => (
              <code key={d} className="mr-1 rounded bg-gray-100 px-1.5 py-0.5 text-xs">{d}</code>
            ))}
          </p>
        )}
        {showRaw && (
          <pre className="mt-2 overflow-auto rounded bg-gray-50 p-2 text-xs">
            {JSON.stringify(agent.raw, null, 2)}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}

export default function AgentsPage() {
  const [bus, setBus] = useState("head-agent");

  const { data, isLoading } = useQuery({
    queryKey: ["agents", bus],
    queryFn: () => getAgents(bus),
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

  const agents = data && !data.error ? data.response.agents : [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Agents</h1>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Bus</CardTitle>
        </CardHeader>
        <CardContent>
          <Input
            value={bus}
            onChange={(e) => setBus(e.target.value)}
            placeholder="head-agent"
            className="max-w-xs"
          />
          <p className="mt-2 text-xs text-gray-400">
            Live view of agents registered on this Messenger bus. Refreshes every 15s.
          </p>
        </CardContent>
      </Card>

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : agents.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-gray-400">
            No agents registered on bus &quot;{bus}&quot;.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {agents.map((agent) => (
            <AgentCard key={agent.agent_id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  );
}
