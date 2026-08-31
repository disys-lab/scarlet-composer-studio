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
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (data && !data.error) {
      setGustavoApiUrl(data.response.gustavo_api_url);
    }
  }, [data]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaved(false);
    try {
      await updateConfig(gustavoApiUrl);
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setSaved(true);
    } finally {
      setSaving(false);
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
            <form onSubmit={handleSave} className="space-y-3 max-w-md">
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
                <Button type="submit" disabled={saving}>
                  {saving ? "Saving…" : "Save"}
                </Button>
              ) : (
                <p className="text-xs text-gray-400">Admin privileges required to change this.</p>
              )}
              {saved && <p className="text-xs text-green-600">Saved.</p>}
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
