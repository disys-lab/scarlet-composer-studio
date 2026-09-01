import apiClient from "./client";
import type { ApiResponse, DashboardStats } from "@/lib/types";

export async function getDashboardStats(): Promise<ApiResponse<DashboardStats>> {
  const res = await apiClient.get("/dashboard/stats");
  return res.data;
}
