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
