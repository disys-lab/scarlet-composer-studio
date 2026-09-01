"use client";
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getConfig, updateConfig } from "@/lib/api/config";
import { useAuth } from "@/lib/context/AuthContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export default function SettingsPage() {
  const { isAdmin } = useAuth();
  const queryClient = useQueryClient();
  const [gustavoApiUrl, setGustavoApiUrl] = useState("");
  const [savingGustavo, setSavingGustavo] = useState(false);
  const [savedGustavo, setSavedGustavo] = useState(false);

  const [redisHost, setRedisHost] = useState("");
  const [redisPort, setRedisPort] = useState("");
  const [redisAuthToken, setRedisAuthToken] = useState("");
  const [redisAuthTokenSet, setRedisAuthTokenSet] = useState(false);
  const [savingRedis, setSavingRedis] = useState(false);
  const [redisResult, setRedisResult] = useState<{ ok: boolean; error?: string | null } | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (data && !data.error) {
      setGustavoApiUrl(data.response.gustavo_api_url);
      setRedisHost(data.response.redis_host);
      setRedisPort(data.response.redis_port);
      setRedisAuthTokenSet(data.response.redis_auth_token_set);
    }
  }, [data]);

  const handleSaveGustavo = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingGustavo(true);
    setSavedGustavo(false);
    try {
      await updateConfig({ gustavo_api_url: gustavoApiUrl });
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setSavedGustavo(true);
    } finally {
      setSavingGustavo(false);
    }
  };

  const handleSaveRedis = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingRedis(true);
    setRedisResult(null);
    try {
      const res = await updateConfig({
        redis_host: redisHost,
        redis_port: redisPort,
        // Empty string means "leave the current token unchanged" - the
        // backend only overwrites it when a real value is sent.
        redis_auth_token: redisAuthToken || undefined,
      });
      if (!res.error) {
        setRedisAuthToken("");
        setRedisAuthTokenSet(res.response.redis_auth_token_set);
        setRedisResult({ ok: !!res.response.redis_ok, error: res.response.redis_error });
      }
      queryClient.invalidateQueries({ queryKey: ["config"] });
    } finally {
      setSavingRedis(false);
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Gustavo API URL</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-9 w-full max-w-md" />
          ) : (
            <form onSubmit={handleSaveGustavo} className="space-y-3 max-w-md">
              <div>
                <Label htmlFor="gustavo_api_url">Gustavo API URL</Label>
                <Input
                  id="gustavo_api_url"
                  value={gustavoApiUrl}
                  onChange={(e) => setGustavoApiUrl(e.target.value)}
                  placeholder="http://127.0.0.1:8000"
                  disabled={!isAdmin}
                  className="mt-1"
                />
                <p className="mt-1 text-xs text-gray-400">
                  Login credentials are checked against this Gustavo instance -
                  the same username/password a Gustavo user already has works here.
                </p>
              </div>
              {isAdmin ? (
                <Button type="submit" disabled={savingGustavo}>
                  {savingGustavo ? "Saving…" : "Save"}
                </Button>
              ) : (
                <p className="text-xs text-gray-400">Admin privileges required to change this.</p>
              )}
              {savedGustavo && <p className="text-xs text-green-600">Saved.</p>}
            </form>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Redis Connection</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-9 w-full max-w-md" />
          ) : (
            <form onSubmit={handleSaveRedis} className="space-y-3 max-w-md">
              <div>
                <Label htmlFor="redis_host">Redis Host</Label>
                <Input
                  id="redis_host"
                  value={redisHost}
                  onChange={(e) => setRedisHost(e.target.value)}
                  placeholder="127.0.0.1"
                  disabled={!isAdmin}
                  className="mt-1"
                />
              </div>
              <div>
                <Label htmlFor="redis_port">Redis Port</Label>
                <Input
                  id="redis_port"
                  value={redisPort}
                  onChange={(e) => setRedisPort(e.target.value)}
                  placeholder="6379"
                  disabled={!isAdmin}
                  className="mt-1"
                />
              </div>
              <div>
                <Label htmlFor="redis_auth_token">Redis Auth Token</Label>
                <Input
                  id="redis_auth_token"
                  type="password"
                  value={redisAuthToken}
                  onChange={(e) => setRedisAuthToken(e.target.value)}
                  placeholder={redisAuthTokenSet ? "•••••••• (set - leave blank to keep)" : "not set"}
                  disabled={!isAdmin}
                  className="mt-1"
                />
                <p className="mt-1 text-xs text-gray-400">
                  Every scarlet Mapper/Federator/Messenger in this deployment reads this
                  connection - changing it takes effect immediately, no restart needed.
                </p>
              </div>
              {isAdmin ? (
                <Button type="submit" disabled={savingRedis}>
                  {savingRedis ? "Saving…" : "Save"}
                </Button>
              ) : (
                <p className="text-xs text-gray-400">Admin privileges required to change this.</p>
              )}
              {redisResult && (
                <p className={`text-xs ${redisResult.ok ? "text-green-600" : "text-red-600"}`}>
                  {redisResult.ok ? "Connected." : `Connection failed: ${redisResult.error}`}
                </p>
              )}
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
