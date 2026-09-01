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

export interface Agent {
  agent_id: string;
  instance_id: string | null;
  scarlet_name: string | null;
  ts: number | null;
  health: "online" | "stale" | "unknown";
  capabilities: string[];
  data_sources: string[];
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
