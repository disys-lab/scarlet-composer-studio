"use client";
import React, { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { login as loginRequest } from "@/lib/api/auth";

// Ported from gustavo-ui/lib/context/AuthContext.tsx, trimmed (no Firebase/
// SSO bridge - not asked for). The credential itself is verified against a
// live Gustavo instance server-side (composer-api/routers/auth.py) - this
// context only deals with composer's own resulting session token.
interface AuthContextValue {
  token: string | null;
  username: string | null;
  isAdmin: boolean;
  isAuthenticated: boolean;
  login: (credential: string) => Promise<{ error: boolean; message?: string }>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const COOKIE_NAME = "composer_token";
// Matches composer-api's default COMPOSER_SESSION_TTL (12h).
const COOKIE_MAX_AGE = 12 * 3600;

function setAuthCookie(token: string) {
  document.cookie = `${COOKIE_NAME}=${token}; path=/; max-age=${COOKIE_MAX_AGE}; SameSite=Lax`;
}

function clearAuthCookie() {
  document.cookie = `${COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax`;
}

function persistSession(token: string, username: string, isAdmin: boolean) {
  localStorage.setItem("composer_token", token);
  localStorage.setItem("composer_username", username);
  localStorage.setItem("composer_is_admin", isAdmin ? "1" : "0");
  setAuthCookie(token);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  // null = not yet fetched from server
  const [authEnabled, setAuthEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    fetch("/api/auth/status")
      .then((r) => r.json())
      .then((data) => setAuthEnabled(data.auth_enabled === true))
      .catch(() => setAuthEnabled(true)); // fail-safe: assume auth required
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedToken = localStorage.getItem("composer_token");
    const storedUsername = localStorage.getItem("composer_username");
    const storedIsAdmin = localStorage.getItem("composer_is_admin");
    if (storedToken) {
      setToken(storedToken);
      setAuthCookie(storedToken);
    }
    if (storedUsername) setUsername(storedUsername);
    setIsAdmin(storedIsAdmin === "1");
  }, []);

  const login = async (credential: string) => {
    try {
      const res = await loginRequest(credential);
      if (res.error) {
        return { error: true, message: String(res.response) };
      }
      const { token: newToken, username: newUsername, is_admin } = res.response;
      persistSession(newToken, newUsername, is_admin);
      setToken(newToken);
      setUsername(newUsername);
      setIsAdmin(is_admin);
      return { error: false };
    } catch (exc) {
      return { error: true, message: String(exc) };
    }
  };

  const logout = () => {
    localStorage.removeItem("composer_token");
    localStorage.removeItem("composer_username");
    localStorage.removeItem("composer_is_admin");
    clearAuthCookie();
    setToken(null);
    setUsername(null);
    setIsAdmin(false);
    if (authEnabled) {
      window.location.href = "/login";
    }
  };

  const isAuthenticated = authEnabled === false || (authEnabled === true && !!token);

  return (
    <AuthContext.Provider value={{ token, username, isAdmin, isAuthenticated, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
