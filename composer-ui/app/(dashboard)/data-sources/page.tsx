"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/context/AuthContext";
import { DataSourceCard } from "@/components/data-sources/DataSourceCard";
import { createDataSource, listDataSources } from "@/lib/api/data-sources";

const fromCsv = (value: string) =>
  value.split(",").map((s) => s.trim()).filter(Boolean);

// Registration here is authorization policy + a directory of broker_urls
// only - see composer-api/data_sources_store.py's docstring. Adding an
// entry never provisions a broker or holds any data-source credential;
// the broker for `name` must already be deployed (like a Gustavo app,
// co-located with the data source it fronts) and pointed at this same
// `name` via its own DATA_SOURCE_NAME env var before any agent can query
// it through here.
function AddDataSourceForm() {
  const [name, setName] = useState("");
  const [type, setType] = useState("mssql");
  const [brokerUrl, setBrokerUrl] = useState("");
  const [description, setDescription] = useState("");
  const [allowedUsers, setAllowedUsers] = useState("");
  const [allowedGroups, setAllowedGroups] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      const res = await createDataSource({
        name,
        type,
        broker_url: brokerUrl,
        description,
        allowed_users: fromCsv(allowedUsers),
        allowed_groups: fromCsv(allowedGroups),
      });
      if (res.error) {
        setMessage(`Failed: ${res.response}`);
      } else {
        setMessage(`Registered "${name}".`);
        setName("");
        setBrokerUrl("");
        setDescription("");
        setAllowedUsers("");
        setAllowedGroups("");
        queryClient.invalidateQueries({ queryKey: ["data-sources"] });
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Register a Data Source</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-3 max-w-md">
          <div>
            <Label htmlFor="ds-name">Name</Label>
            <Input
              id="ds-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="warehouse_dw"
              className="mt-1 font-mono"
              required
            />
            <p className="mt-1 text-xs text-gray-400">
              Must match the broker&apos;s own DATA_SOURCE_NAME env var exactly.
            </p>
          </div>
          <div>
            <Label htmlFor="ds-type">Type</Label>
            <Input
              id="ds-type"
              value={type}
              onChange={(e) => setType(e.target.value)}
              placeholder="mssql"
              className="mt-1"
              required
            />
          </div>
          <div>
            <Label htmlFor="ds-broker-url">Broker URL</Label>
            <Input
              id="ds-broker-url"
              value={brokerUrl}
              onChange={(e) => setBrokerUrl(e.target.value)}
              placeholder="http://10.0.1.20:8090"
              className="mt-1 font-mono"
              required
            />
            <p className="mt-1 text-xs text-gray-400">
              Where the broker for this data source is deployed - reachable directly by agents,
              not through composer-api.
            </p>
          </div>
          <div>
            <Label htmlFor="ds-description">Description</Label>
            <textarea
              id="ds-description"
              className="mt-1 w-full min-h-16 rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this data source is, and what an agent should expect from it."
            />
          </div>
          <div>
            <Label htmlFor="ds-allowed-users">Allowed users (comma-separated)</Label>
            <Input
              id="ds-allowed-users"
              value={allowedUsers}
              onChange={(e) => setAllowedUsers(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="ds-allowed-groups">Allowed Nebula groups (comma-separated)</Label>
            <Input
              id="ds-allowed-groups"
              value={allowedGroups}
              onChange={(e) => setAllowedGroups(e.target.value)}
              className="mt-1"
            />
          </div>
          <Button type="submit" disabled={saving || !name || !brokerUrl}>
            {saving ? "Registering…" : "Register"}
          </Button>
          {message && <p className="text-xs text-muted-foreground">{message}</p>}
        </form>
      </CardContent>
    </Card>
  );
}

export default function DataSourcesPage() {
  const { isAdmin } = useAuth();
  const { data, isLoading } = useQuery({
    queryKey: ["data-sources"],
    queryFn: listDataSources,
    staleTime: 30_000,
  });

  const dataSources = data && !data.error ? data.response.data_sources : [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Data Sources</h1>
      <p className="text-sm text-gray-400 max-w-2xl">
        Each data source is fronted by its own broker, deployed co-located with the data itself.
        Composer-api only holds registration + access policy here - it is never in the path of an
        actual query. An agent with a Nebula identity in an allowed user or group below can query
        the corresponding broker directly.
      </p>

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : dataSources.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-gray-400">
            No data sources registered yet.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {dataSources.map((ds) => (
            <DataSourceCard key={ds.name} dataSource={ds} />
          ))}
        </div>
      )}

      {isAdmin && <AddDataSourceForm />}
    </div>
  );
}
