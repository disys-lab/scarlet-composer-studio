import apiClient from "./client";
import type { ApiResponse, ComposerConfig } from "@/lib/types";

export const getConfig = () =>
  apiClient.get<ApiResponse<ComposerConfig>>("/config").then((r) => r.data);

export const updateConfig = (gustavo_api_url: string) =>
  apiClient.put<ApiResponse<ComposerConfig>>("/config", { gustavo_api_url }).then((r) => r.data);
