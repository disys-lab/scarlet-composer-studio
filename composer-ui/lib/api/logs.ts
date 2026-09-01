import apiClient from "./client";
import type { ApiResponse, LogsResponse } from "@/lib/types";

export const listLogs = () =>
  apiClient.get<ApiResponse<LogsResponse>>("/logs").then((r) => r.data);
