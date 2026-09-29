// Matches composer-api's response envelope (main.py / routers/*.py),
// same {error, response} contract gustavo-ui's own backend uses.
export type ApiResponse<T> = { error: boolean; response: T };

export interface DashboardStats {
  redis_ok: boolean;
  redis_error: string | null;
  agent_count: number;
  agent_bus: string;
  scarlet_count: number;
}

// Redacted view of a worker's own ~/.scarlet/config.yaml entries - no
// credential fields, ever (see scarlet-agentic-harness's
// local_config.describe_sources()). "broker" entries relay through a
// centralized broker (see the Data Sources tab's own registry); "local"
// entries are queried by this worker directly, in-process.
export interface AgentDataSource {
  name: string;
  type: string;
  mode: "local" | "broker";
  description: string;
}

// One in-flight request on an agent, as published to its activity Mapper
// (see the harness's cancellation.py). progress_snapshot() merges extra
// per-skill fields in, so this is deliberately open-ended beyond the two
// that are always present.
export interface AgentInFlight {
  skill: string;
  elapsed_seconds: number;
  [key: string]: unknown;
}

export interface AgentActivity {
  in_flight: Record<string, AgentInFlight>;
  count: number;
}

export interface Agent {
  agent_id: string;
  instance_id: string | null;
  scarlet_name: string | null;
  ts: number | null;
  health: "online" | "stale" | "unknown";
  capabilities: string[];
  data_sources: AgentDataSource[];
  // null on an agent that publishes no activity at all - a head, or an
  // agent on an image predating activity_mapper reporting. An agent that
  // publishes but is idle has count 0 and an empty in_flight, which is a
  // different thing and renders differently.
  activity: AgentActivity | null;
  raw: Record<string, unknown>;
}

export interface AgentsResponse {
  bus: string;
  agents: Agent[];
  // True when no scarlet_definition_ entry exists for this bus, i.e.
  // nobody has ever created it - distinct from a real bus that currently
  // has no agents on it. Lets the UI say which of the two it is.
  unknown_bus: boolean;
}

export interface AuthStatus {
  auth_enabled: boolean;
}

export interface LoginResponse {
  token: string;
  username: string;
  is_admin: boolean;
}

export interface ComposerConfig {
  gustavo_api_url: string;
  redis_host: string;
  redis_port: string;
  redis_auth_token_set: boolean;
  // Present only on the PUT response (a live connection test runs on every save).
  redis_ok?: boolean;
  redis_error?: string | null;
}

export interface Scarlet {
  name: string;
  scarlet_type: string;
  mode: string;
  description: string;
  attributes: Record<string, unknown>;
  created_by: string | null;
  created_at: number | null;
}

export interface ScarletsResponse {
  scarlets: Scarlet[];
}

// Shape returned by POST /api/scarlets/interpret - keyed by scarlet name,
// matching ScarletInterpreter.scarletContent's own shape exactly (so the
// same object round-trips straight into POST /api/scarlets/deploy).
export interface InterpretedScarlet {
  scarlet_type: string;
  scarlet_name: string;
  scarlet_attributes: Record<string, unknown>;
  content: string;
  description: string;
}

export type InterpretedScarlets = Record<string, InterpretedScarlet>;

export interface LogEntry {
  id: string;
  time: number;
  app: string;
  node: string;
  level: string;
  msg: string;
  filename: string;
  line: string;
}

export interface LogsResponse {
  logs: LogEntry[];
}

// Matches composer-api's routers/data_sources.py _public_shape() exactly -
// no credential field exists on this entry anywhere (see
// composer-api/data_sources_store.py's docstring): the broker at
// broker_url holds its own data-source credential entirely on its own,
// configured at that broker's own deployment time.
export interface DataSource {
  name: string;
  type: string;
  broker_url: string;
  description: string;
  allowed_users: string[];
  allowed_groups: string[];
}

export interface DataSourcesResponse {
  data_sources: DataSource[];
}

// ─── Conversations ──────────────────────────────────────────────────────────
// Reconstructed from the messages Redis already holds - see
// composer-api/conversations.py for how a conversation is put back together
// and why the "dispatch" event is the only thing that makes it possible.

// One message on the bus, as shown inside an attempt.
export interface ConversationMessage {
  ts: number | null;
  from: string | null;
  to: string | null;
  bus: string | null;
  type: string | null;
  // "dialogue" is the plain-English check-in traffic; "dispatch" is the
  // coordinate/contribute/result envelope. Rendered differently.
  kind: "reasoning" | "dialogue" | "dispatch" | "other";
  content: string | null;
  body: Record<string, unknown>;
}

// One run_skill attempt. A retried call has more than one, each with its
// own request_id - which is why the correlation exists at all.
export interface ConversationAttempt {
  request_id: string | null;
  attempt: number | null;
  messages: ConversationMessage[];
}

export interface ConversationTurn {
  kind: "narration" | "tool_call" | "final" | "orphan_dispatch";
  ts: number | null;
  content?: string | null;
  call_id?: string | null;
  skill?: string | null;
  params?: Record<string, unknown> | null;
  attempts?: ConversationAttempt[];
  result?: unknown;
  result_summary?: string | null;
  request_id?: string | null;
}

export interface ConversationDetail {
  conv_id: string;
  question: string | null;
  answer: string | null;
  started_at: number | null;
  ended_at: number | null;
  status: "answered" | "incomplete";
  turns: ConversationTurn[];
}

export interface ConversationSummary {
  conv_id: string;
  answer: string | null;
  status: "answered" | "incomplete";
  started_at: number | null;
  ended_at: number | null;
  duration: number | null;
  skills: (string | null)[];
  call_count: number;
  // More attempts than calls means something was retried - the signal
  // worth surfacing without opening the conversation.
  attempt_count: number;
}

// Dispatch traffic belonging to no conversation we can see: a fleet with
// PUBLISH_REASONING off, agents on an older image, or a skill invoked
// outside a conversation. Shown rather than hidden.
export interface UnattributedRequest {
  request_id: string;
  started_at: number | null;
  message_count: number;
  messages: ConversationMessage[];
}

export interface ConversationsResponse {
  conversations: ConversationSummary[];
  unattributed: UnattributedRequest[];
  buses: string[];
  unknown_bus: boolean;
}
