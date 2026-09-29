import apiClient from "./client";
import type { ApiResponse, DashboardStats } from "@/lib/types";

// The bus is passed explicitly rather than left to the endpoint's own
// default. That default is a conventional name no real deployment
// necessarily uses, which is why this card reported 0 agents against a
// healthy fleet - it was counting a bus nobody had joined. The caller
// supplies whichever bus the operator selected on the Agents page.
export async function getDashboardStats(bus: string): Promise<ApiResponse<DashboardStats>> {
  const res = await apiClient.get("/dashboard/stats", { params: { bus } });
  return res.data;
}
