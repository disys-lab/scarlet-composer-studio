import apiClient from "./client";
import type { ApiResponse, AuthStatus, LoginResponse } from "@/lib/types";

export const getAuthStatus = () =>
  apiClient.get<AuthStatus>("/auth/status").then((r) => r.data);

// credential is "identifier:secret" - whatever a Gustavo user already logs
// into Gustavo with. composer-api forwards this to a live Gustavo
// instance's own /api/auth/login and only mints a session if Gustavo
// itself says the credential is valid - see composer-api/routers/auth.py.
export const login = (credential: string) =>
  apiClient
    .post<ApiResponse<LoginResponse>>("/auth/login", { credential })
    .then((r) => r.data);
