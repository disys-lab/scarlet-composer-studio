"use client";
import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/context/AuthContext";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";

// Ported from gustavo-ui/app/login/page.tsx, trimmed (no Firebase/SSO
// section - not asked for). The credential typed here is whatever a
// Gustavo user already logs into Gustavo with - composer-api forwards it
// to a live Gustavo instance to actually check it.
function LoginForm() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const goToDestination = () => {
    const redirect = searchParams.get("redirect") ?? "/dashboard";
    router.push(redirect);
  };

  // Credentials are generated/displayed elsewhere as one "username:token"
  // string - if someone pastes the whole thing into either field, split it
  // into both instead of treating the colon as a literal character.
  const applyPastedCredential = (value: string): boolean => {
    const idx = value.indexOf(":");
    if (idx === -1) return false;
    setUsername(value.slice(0, idx));
    setPassword(value.slice(idx + 1));
    return true;
  };

  const handleUsernameChange = (value: string) => {
    if (!applyPastedCredential(value)) setUsername(value);
  };

  const handlePasswordChange = (value: string) => {
    if (!applyPastedCredential(value)) setPassword(value);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const result = await login(`${username}:${password}`);
    setLoading(false);
    if (result.error) {
      setError(result.message ?? "Login failed");
    } else {
      goToDestination();
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="w-full max-w-sm rounded-xl border bg-white p-8 shadow-sm">
        <div className="mb-6 flex justify-center">
          <span className="text-2xl font-semibold text-gray-900">Scarlet Composer</span>
        </div>
        <h1 className="mb-1 text-center text-xl font-bold text-gray-900">Sign in</h1>
        <p className="mb-6 text-center text-sm text-gray-500">
          Sign in with your Gustavo credentials
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              type="text"
              value={username}
              onChange={(e) => handleUsernameChange(e.target.value)}
              placeholder="nebula"
              required
              autoComplete="username"
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="password">Password / token</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => handlePasswordChange(e.target.value)}
              required
              autoComplete="current-password"
              className="mt-1"
            />
            <p className="mt-1 text-xs text-gray-400">
              Platform admin default is nebula / nebula. You can also paste your
              full username:token credential into either field.
            </p>
          </div>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
