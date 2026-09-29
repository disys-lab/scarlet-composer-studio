"use client";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getConversations, getConversation } from "@/lib/api/conversations";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import type {
  ConversationAttempt, ConversationMessage, ConversationSummary, ConversationTurn,
} from "@/lib/types";

// What the agents actually said to each other, reconstructed from the
// messages Redis already holds.
//
// The Logging page shows the same underlying system as a flat chronological
// stream, which is unreadable the moment two requests overlap. This shows
// one conversation at a time: the head's reasoning, and the dispatch each
// decision caused, nested under the decision.

// Same key the Agents page persists its bus under, read directly rather
// than through a shared module so this page carries no dependency on it.
const BUS_KEY = "scarlet-composer.agents.bus";
const LOCAL_BUS_KEY = "scarlet-composer.conversations.localBus";

function ts(v: number | null | undefined) {
  if (!v) return "";
  return new Date(v * 1000).toLocaleTimeString();
}

function duration(d: number | null) {
  if (d === null || d === undefined) return "";
  return d < 1 ? `${Math.round(d * 1000)}ms` : `${d.toFixed(1)}s`;
}

function MessageLine({ m }: { m: ConversationMessage }) {
  // Check-in dialogue is the readable part - the head asking a coordinator
  // what is happening and the reply, both plain English. Given room here;
  // envelopes get one dense line.
  if (m.kind === "dialogue" && m.content) {
    return (
      <div className="rounded border-l-2 border-blue-300 bg-blue-50/50 px-3 py-2">
        <div className="text-xs text-gray-500">
          {m.from} → {m.to} · {ts(m.ts)}
        </div>
        <p className="mt-1 text-sm text-gray-800">{m.content}</p>
      </div>
    );
  }
  return (
    <div className="flex items-baseline gap-2 px-3 py-1 text-xs">
      <code className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5">{m.type}</code>
      <span className="truncate text-gray-500">
        {m.from} → {m.to}
      </span>
      <span className="ml-auto shrink-0 tabular-nums text-gray-400">{ts(m.ts)}</span>
    </div>
  );
}

function AttemptBlock({ a, showAttemptNumber }: { a: ConversationAttempt; showAttemptNumber: boolean }) {
  return (
    <div className="mt-2 rounded border border-gray-200">
      <div className="flex items-center gap-2 border-b border-gray-100 bg-gray-50 px-3 py-1.5 text-xs">
        {showAttemptNumber && (
          // Only shown when there was more than one - a retry is the thing
          // worth noticing, and labelling a solitary attempt "attempt 1"
          // implies a problem that is not there.
          <span className="rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-900">
            attempt {a.attempt}
          </span>
        )}
        <code className="text-gray-500">{a.request_id?.slice(0, 8)}…</code>
        <span className="ml-auto text-gray-400">
          {a.messages.length} message{a.messages.length === 1 ? "" : "s"}
        </span>
      </div>
      {a.messages.length === 0 ? (
        <p className="px-3 py-2 text-xs text-gray-400">
          No bus traffic found for this attempt — it may have expired with the bus TTL.
        </p>
      ) : (
        <div className="divide-y divide-gray-50 py-1">
          {a.messages.map((m, i) => (
            <MessageLine key={i} m={m} />
          ))}
        </div>
      )}
    </div>
  );
}

function TurnBlock({ t }: { t: ConversationTurn }) {
  if (t.kind === "narration") {
    return (
      <div className="border-l-2 border-gray-300 py-1 pl-3">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-400">thinking</span>
        <p className="text-sm text-gray-700">{t.content}</p>
      </div>
    );
  }
  if (t.kind === "final") {
    return (
      <div className="rounded border-l-2 border-green-400 bg-green-50/50 px-3 py-2">
        <span className="text-xs font-medium uppercase tracking-wide text-green-700">answer</span>
        <p className="mt-1 text-sm text-gray-900">{t.content}</p>
      </div>
    );
  }
  if (t.kind === "orphan_dispatch") {
    return (
      <div className="rounded border border-dashed border-gray-300 px-3 py-2">
        <p className="text-xs text-gray-500">
          Dispatch <code>{t.request_id?.slice(0, 8)}…</code> with no matching tool call — the
          inbox holding it has probably partly expired.
        </p>
      </div>
    );
  }

  const attempts = t.attempts ?? [];
  return (
    <div className="rounded border border-gray-200 p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <code className="rounded bg-indigo-50 px-1.5 py-0.5 text-sm font-medium text-indigo-900">
          {t.skill}
        </code>
        <code className="text-xs text-gray-500">{JSON.stringify(t.params ?? {})}</code>
        {t.result_summary && (
          <span className="ml-auto text-sm tabular-nums text-gray-700">→ {t.result_summary}</span>
        )}
      </div>
      {attempts.map((a, i) => (
        <AttemptBlock key={i} a={a} showAttemptNumber={attempts.length > 1} />
      ))}
    </div>
  );
}

function ConversationDetailView({
  convId, bus, localBus, onBack,
}: { convId: string; bus: string; localBus: string; onBack: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["conversation", convId, bus, localBus],
    queryFn: () => getConversation(convId, bus, localBus),
  });

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (!data || data.error) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-gray-500">
          {data?.error ? String(data.response) : "Could not load this conversation."}
          <button onClick={onBack} className="ml-2 text-blue-600 hover:underline">
            back
          </button>
        </CardContent>
      </Card>
    );
  }

  const c = data.response;
  return (
    <div className="space-y-4">
      <button onClick={onBack} className="text-sm text-blue-600 hover:underline">
        ← all conversations
      </button>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{c.question || "(question not recorded)"}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-gray-500">
            <code>{c.conv_id}</code> · {ts(c.started_at)}
            {c.status === "incomplete" && (
              <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-amber-900">
                no final answer
              </span>
            )}
          </p>
        </CardContent>
      </Card>

      <div className="space-y-3">
        {c.turns.map((t, i) => (
          <TurnBlock key={i} t={t} />
        ))}
      </div>
    </div>
  );
}

function SummaryRow({ c, onOpen }: { c: ConversationSummary; onOpen: () => void }) {
  const retried = c.attempt_count > c.call_count;
  return (
    <button
      onClick={onOpen}
      className="w-full rounded border border-gray-200 p-3 text-left hover:border-gray-300 hover:bg-gray-50"
    >
      <div className="flex items-baseline gap-2">
        <span className="truncate text-sm font-medium text-gray-900">
          {c.answer || "(no answer recorded)"}
        </span>
        <span className="ml-auto shrink-0 text-xs tabular-nums text-gray-400">
          {duration(c.duration)}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-gray-500">
        <span>{ts(c.started_at)}</span>
        {c.skills.filter(Boolean).map((s, i) => (
          <code key={i} className="rounded bg-gray-100 px-1.5 py-0.5">
            {s}
          </code>
        ))}
        {retried && (
          // Surfaced in the list because a retry is usually why someone is
          // looking - it means an attempt went unanswered.
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-900">
            {c.attempt_count} attempts for {c.call_count} call{c.call_count === 1 ? "" : "s"}
          </span>
        )}
        {c.status === "incomplete" && (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-900">incomplete</span>
        )}
      </div>
    </button>
  );
}

export default function ConversationsPage() {
  const [busInput, setBusInput] = useState("");
  const [localInput, setLocalInput] = useState("");
  const [bus, setBus] = useState("");
  const [localBus, setLocalBus] = useState("");
  const [restored, setRestored] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  // Read in an effect, not in useState: this page pre-renders on the
  // server where localStorage does not exist.
  useEffect(() => {
    try {
      const b = window.localStorage.getItem(BUS_KEY) || "";
      const l = window.localStorage.getItem(LOCAL_BUS_KEY) || "";
      setBusInput(b);
      setBus(b);
      setLocalInput(l);
      setLocalBus(l);
    } catch {
      // Private browsing or storage disabled - start empty.
    }
    setRestored(true);
  }, []);

  function save() {
    const b = busInput.trim();
    const l = localInput.trim();
    setBus(b);
    setLocalBus(l);
    try {
      window.localStorage.setItem(BUS_KEY, b);
      window.localStorage.setItem(LOCAL_BUS_KEY, l);
    } catch {
      // Not fatal - the choice just will not survive a reload.
    }
  }

  const dirty = busInput.trim() !== bus || localInput.trim() !== localBus;

  const { data, isLoading } = useQuery({
    queryKey: ["conversations", bus, localBus],
    queryFn: () => getConversations(bus, localBus),
    // Only query a bus that has been named. Sending an empty one would be
    // a guaranteed miss, and the endpoint requires it.
    enabled: restored && bus.length > 0 && !openId,
    refetchInterval: 20_000,
    staleTime: 15_000,
  });

  const res = data && !data.error ? data.response : undefined;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Conversations</h1>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Buses</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={busInput}
              onChange={(e) => setBusInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && save()}
              placeholder="head bus (HEAD_BUS)"
              className="max-w-xs"
            />
            <Input
              value={localInput}
              onChange={(e) => setLocalInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && save()}
              placeholder="device-group bus (DEVICE_GROUP), optional"
              className="max-w-xs"
            />
            <Button onClick={save} disabled={!dirty} size="sm">
              Save
            </Button>
          </div>
          <p className="mt-2 text-xs text-gray-500">
            Dispatch and check-ins ride the head bus; contributor handshakes ride the
            device-group bus. A stalled skill often shows up only in the second.
          </p>
        </CardContent>
      </Card>

      {!bus ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-gray-400">
            Name a head bus above to see conversations.
          </CardContent>
        </Card>
      ) : openId ? (
        <ConversationDetailView
          convId={openId}
          bus={bus}
          localBus={localBus}
          onBack={() => setOpenId(null)}
        />
      ) : isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : res?.unknown_bus ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-gray-400">
            No bus named &quot;{bus}&quot; exists yet — a bus is created by the first agent
            that joins it.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {res && res.conversations.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-sm text-gray-400">
                No conversations on this bus yet. They appear once a head answers a
                question — set <code>PUBLISH_REASONING</code> if the head is running with
                it disabled.
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-2">
              {res?.conversations.map((c) => (
                <SummaryRow key={c.conv_id} c={c} onOpen={() => setOpenId(c.conv_id)} />
              ))}
            </div>
          )}

          {res && res.unattributed.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Unattributed dispatch</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="mb-3 text-xs text-gray-500">
                  Traffic belonging to no conversation we can see — normal when the head
                  runs with <code>PUBLISH_REASONING=false</code>, when an agent is on an
                  older image, or when a skill was dispatched outside a conversation.
                </p>
                <div className="space-y-1">
                  {res.unattributed.map((u) => (
                    <div key={u.request_id} className="flex items-baseline gap-2 text-xs">
                      <code className="rounded bg-gray-100 px-1.5 py-0.5">
                        {u.request_id.slice(0, 12)}…
                      </code>
                      <span className="text-gray-500">
                        {u.message_count} message{u.message_count === 1 ? "" : "s"}
                      </span>
                      <span className="ml-auto text-gray-400">{ts(u.started_at)}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
