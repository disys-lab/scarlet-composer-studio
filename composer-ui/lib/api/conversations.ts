import apiClient from "./client";
import type { ApiResponse, ConversationDetail, ConversationsResponse } from "@/lib/types";

// Both buses are passed: dispatch and check-ins ride the head bus,
// contributor handshakes ride the device-group bus, and a stalled skill
// often shows up only in the second.
export async function getConversations(
  bus: string, localBus?: string, limit = 50,
): Promise<ApiResponse<ConversationsResponse>> {
  const res = await apiClient.get("/conversations", {
    params: { bus, local_bus: localBus || undefined, limit },
  });
  return res.data;
}

export async function getConversation(
  convId: string, bus: string, localBus?: string,
): Promise<ApiResponse<ConversationDetail>> {
  const res = await apiClient.get(`/conversations/${encodeURIComponent(convId)}`, {
    params: { bus, local_bus: localBus || undefined },
  });
  return res.data;
}
