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

export const interpretScarletsFile = (file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  return apiClient
    .post<ApiResponse<{ scarlets: InterpretedScarlets }>>("/scarlets/interpret/upload", formData, {
      // Must NOT set Content-Type explicitly here - the browser derives
      // "multipart/form-data; boundary=..." itself from the FormData body,
      // and a manually-set header (even the "right" string, missing the
      // boundary) breaks server-side multipart parsing. `undefined`
      // overrides the apiClient instance's default application/json.
      headers: { "Content-Type": undefined },
    })
    .then((r) => r.data);
};

export const deployScarlets = (scarlets: InterpretedScarlets) =>
  apiClient
    .post<ApiResponse<{ deployed: string[] }>>("/scarlets/deploy", { scarlets })
    .then((r) => r.data);
