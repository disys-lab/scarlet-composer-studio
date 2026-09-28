"use client";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getAgents } from "@/lib/api/agents";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/StatusPill";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import type { Agent } from "@/lib/types";

// Replaces scarletcomposer/pages/Agents.py. Auto-refresh via React Query's
// refetchInterval (matches the old page's 15s cadence) instead of a
// manual sleep()+st.rerun() loop.

// Where the tracked bus is remembered between visits. Per-browser, which
// is the right scope for "which bus am I looking at" - a view preference,
// not deployment state, and it needs no API surface to store.
const BUS_STORAGE_KEY = "scarlet-composer.agents.bus";
const DEFAULT_BUS = "head-agent";

function ageLabel(ts: number | null) {
  if (!ts) return "unknown";
  const age = Date.now() / 1000 - ts;
  if (age < 60) return `${Math.floor(age)}s ago`;
  if (age < 3600) return `${Math.floor(age / 60)}m ago`;
  return `${Math.floor(age / 3600)}h ago`;
}

function elapsedLabel(seconds: number) {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
}

// Three genuinely different states, deliberately rendered differently: no
// activity field at all (this agent publishes none - a head, or an older
// image), publishing but idle, and actually running something.
function ActivitySection({ agent }: { agent: Agent }) {
  if (!agent.activity) {
    return (
      <p className="text-xs text-gray-400">
        <span className="font-medium">Activity:</span> not reported
      </p>
    );
  }
  const entries = Object.entries(agent.activity.in_flight ?? {});
  if (entries.length === 0) {
    return (
      <p className="text-xs text-gray-500">
        <span className="font-medium">Activity:</span> idle
      </p>
    );
  }
  return (
    <div className="text-sm">
      <span className="font-medium">Activity: {agent.activity.count} in flight</span>
      <ul className="mt-1 space-y-1">
        {entries.map(([requestId, inFlight]) => (
          <li key={requestId} className="flex items-baseline gap-1.5">
            <code className="shrink-0 rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-900">
              {inFlight.skill}
            </code>
            <span className="text-xs tabular-nums text-gray-500">
              {elapsedLabel(inFlight.elapsed_seconds)}
            </span>
            <span className="truncate font-mono text-xs text-gray-400">
              {requestId.slice(0, 8)}…
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
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
        <ActivitySection agent={agent} />
        {agent.capabilities.length > 0 && (
          <p className="text-sm">
            <span className="font-medium">Capabilities:</span>{" "}
            {agent.capabilities.map((c) => (
              <code key={c} className="mr-1 rounded bg-gray-100 px-1.5 py-0.5 text-xs">{c}</code>
            ))}
          </p>
        )}
        {agent.data_sources.length > 0 && (
          <div className="text-sm">
            <span className="font-medium">Data sources:</span>
            <ul className="mt-1 space-y-1">
              {agent.data_sources.map((d) => (
                <li key={d.name} className="flex items-start gap-1.5">
                  <code className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs">{d.name}</code>
                  <span className="text-xs text-gray-400">
                    {d.type} · {d.mode}
                    {d.description && <> — {d.description}</>}
                  </span>
                </li>
              ))}
            </ul>
          </div>
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
  // Two separate pieces of state on purpose. The query keys on activeBus
  // alone, so typing changes nothing until Save. Keying it on the input
  // instead - as this page used to - fired a request per keystroke, and
  // each one made composer-api construct a Messenger for whatever prefix
  // had been typed so far, permanently creating a scarlet definition and
  // a heartbeat thread for "s", "sc", "sca"... The API now refuses buses
  // that don't exist (see bus_registry.bus_exists), but not sending them
  // in the first place is the actual fix.
  const [busInput, setBusInput] = useState(DEFAULT_BUS);
  const [activeBus, setActiveBus] = useState(DEFAULT_BUS);
  const [restored, setRestored] = useState(false);

  // Read in an effect, not in useState's initializer: this component
  // pre-renders on the server, where localStorage does not exist, and
  // seeding initial state from it would mismatch the first client render.
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(BUS_STORAGE_KEY);
      if (saved) {
        setBusInput(saved);
        setActiveBus(saved);
      }
    } catch {
      // Private browsing or storage disabled - fall back to the default.
    }
    setRestored(true);
  }, []);

  const dirty = busInput.trim() !== activeBus && busInput.trim().length > 0;

  function save() {
    const next = busInput.trim();
    if (!next || next === activeBus) return;
    setActiveBus(next);
    try {
      window.localStorage.setItem(BUS_STORAGE_KEY, next);
    } catch {
      // Not fatal - the bus just won't be remembered next visit.
    }
  }

  const { data, isLoading } = useQuery({
    queryKey: ["agents", activeBus],
    queryFn: () => getAgents(activeBus),
    // Hold until localStorage has been consulted, or every page load
    // would query the default bus once regardless of what was saved.
    enabled: restored,
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

  const agents = data && !data.error ? data.response.agents : [];
  const unknownBus = data && !data.error ? data.response.unknown_bus : false;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Agents</h1>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Bus</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <Input
              value={busInput}
              onChange={(e) => setBusInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
              }}
              placeholder="scarlet-agent-tutorial_headagent"
              className="max-w-md"
            />
            <Button onClick={save} disabled={!dirty} size="sm">
              Save
            </Button>
          </div>
          <p className="mt-2 text-xs text-gray-500">
            Tracking <code className="rounded bg-gray-100 px-1.5 py-0.5">{activeBus}</code>
            {" · "}refreshes every 15s
          </p>
          {dirty && (
            <p className="mt-1 text-xs text-amber-600">
              Unsaved — press Save or Enter to track{" "}
              <code className="rounded bg-amber-50 px-1.5 py-0.5">{busInput.trim()}</code>
            </p>
          )}
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
            {unknownBus ? (
              <>
                No bus named &quot;{activeBus}&quot; exists yet — a bus is created by
                the first agent that joins it. Check the name, or see the
                Scarlets page for the buses that do exist.
              </>
            ) : (
              <>No agents registered on bus &quot;{activeBus}&quot;.</>
            )}
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
