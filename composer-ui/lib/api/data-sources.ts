import apiClient from "./client";
import type { ApiResponse, DataSource, DataSourcesResponse } from "@/lib/types";

export const listDataSources = () =>
  apiClient.get<ApiResponse<DataSourcesResponse>>("/data-sources").then((r) => r.data);

export type DataSourceInput = Omit<DataSource, "allowed_users" | "allowed_groups"> & {
  allowed_users: string[];
  allowed_groups: string[];
};

export const createDataSource = (entry: DataSourceInput) =>
  apiClient.post<ApiResponse<DataSource>>("/data-sources", entry).then((r) => r.data);

export const updateDataSource = (name: string, entry: Partial<DataSourceInput>) =>
  apiClient.put<ApiResponse<DataSource>>(`/data-sources/${encodeURIComponent(name)}`, entry).then((r) => r.data);

export const deleteDataSource = (name: string) =>
  apiClient.delete<ApiResponse<{ deleted: string }>>(`/data-sources/${encodeURIComponent(name)}`).then((r) => r.data);
