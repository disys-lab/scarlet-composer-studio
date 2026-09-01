import apiClient from "./client";
import type { ApiResponse, ComposerConfig } from "@/lib/types";

export const getConfig = () =>
  apiClient.get<ApiResponse<ComposerConfig>>("/config").then((r) => r.data);

export interface ConfigUpdate {
  gustavo_api_url?: string;
  redis_host?: string;
  redis_port?: string;
  // Omit or leave empty to keep the currently-set token unchanged.
  redis_auth_token?: string;
}

export const updateConfig = (update: ConfigUpdate) =>
  apiClient.put<ApiResponse<ComposerConfig>>("/config", update).then((r) => r.data);
