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

export interface Agent {
  agent_id: string;
  instance_id: string | null;
  scarlet_name: string | null;
  ts: number | null;
  health: "online" | "stale" | "unknown";
  capabilities: string[];
  data_sources: AgentDataSource[];
  raw: Record<string, unknown>;
}

export interface AgentsResponse {
  bus: string;
  agents: Agent[];
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
