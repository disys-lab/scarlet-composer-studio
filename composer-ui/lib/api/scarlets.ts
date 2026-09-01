import apiClient from "./client";
import type { ApiResponse, InterpretedScarlets, ScarletsResponse } from "@/lib/types";

export const listScarlets = () =>
  apiClient.get<ApiResponse<ScarletsResponse>>("/scarlets").then((r) => r.data);

export const updateScarletDescription = (name: string, description: string) =>
  apiClient
    .put<ApiResponse<{ name: string; description: string }>>(`/scarlets/${encodeURIComponent(name)}/description`, { description })
    .then((r) => r.data);

export const deleteScarlet = (name: string) =>
  apiClient
    .delete<ApiResponse<{ deleted: string[] }>>(`/scarlets/${encodeURIComponent(name)}`)
    .then((r) => r.data);

export const resetScarlet = (name: string) =>
  apiClient
    .post<ApiResponse<{ cleared_chunks: number }>>(`/scarlets/${encodeURIComponent(name)}/reset`)
    .then((r) => r.data);

export const interpretScarlets = (path: string) =>
  apiClient
    .post<ApiResponse<{ scarlets: InterpretedScarlets }>>("/scarlets/interpret", { path })
    .then((r) => r.data);

export const deployScarlets = (scarlets: InterpretedScarlets) =>
  apiClient
    .post<ApiResponse<{ deployed: string[] }>>("/scarlets/deploy", { scarlets })
    .then((r) => r.data);
