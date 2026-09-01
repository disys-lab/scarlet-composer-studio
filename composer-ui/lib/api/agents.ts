import apiClient from "./client";
import type { AgentsResponse, ApiResponse } from "@/lib/types";

export async function getAgents(bus: string): Promise<ApiResponse<AgentsResponse>> {
  const res = await apiClient.get("/agents", { params: { bus } });
  return res.data;
}
