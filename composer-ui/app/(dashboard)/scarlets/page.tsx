"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ScarletCard } from "@/components/scarlets/ScarletCard";
import { deployScarlets, interpretScarlets, interpretScarletsFile, listScarlets } from "@/lib/api/scarlets";
import type { InterpretedScarlets } from "@/lib/types";

// Replaces scarletcomposer/Scarlets.py's View + Deploy tabs (Container
// Builds is its own separate page - see the Sidebar). Deploy is stateless
// here, unlike Streamlit's session_state-held interpreter instance:
// interpret returns a preview to the browser; deploy sends back whatever
// the operator reviewed/edited.
function ViewTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["scarlets"],
    queryFn: listScarlets,
    refetchInterval: 15_000,
  });

  const scarlets = data && !data.error ? data.response.scarlets : [];

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }

  if (scarlets.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-gray-400">
          No scarlet definitions registered yet.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {scarlets.map((scarlet) => (
        <ScarletCard key={scarlet.name} scarlet={scarlet} />
      ))}
    </div>
  );
}

function DeployTab() {
  const [path, setPath] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [interpreting, setInterpreting] = useState(false);
  const [interpreted, setInterpreted] = useState<InterpretedScarlets | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deploying, setDeploying] = useState(false);
  const [deployMessage, setDeployMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleInterpretUpload = async () => {
    if (!file) return;
    setInterpreting(true);
    setError(null);
    setDeployMessage(null);
    try {
      const res = await interpretScarletsFile(file);
      if (res.error) {
        setError(String(res.response));
        setInterpreted(null);
      } else {
        setInterpreted(res.response.scarlets);
      }
    } finally {
      setInterpreting(false);
    }
  };

  const handleInterpretPath = async () => {
    setInterpreting(true);
    setError(null);
    setDeployMessage(null);
    try {
      const res = await interpretScarlets(path);
      if (res.error) {
        setError(String(res.response));
        setInterpreted(null);
      } else {
        setInterpreted(res.response.scarlets);
      }
    } finally {
      setInterpreting(false);
    }
  };

  const updateDescription = (name: string, description: string) => {
    if (!interpreted) return;
    setInterpreted({ ...interpreted, [name]: { ...interpreted[name], description } });
  };

  const handleDeploy = async () => {
    if (!interpreted) return;
    setDeploying(true);
    setDeployMessage(null);
    try {
      const res = await deployScarlets(interpreted);
      if (res.error) {
        setDeployMessage(`Deploy failed: ${res.response}`);
      } else {
        setDeployMessage(`Deployed: ${res.response.deployed.join(", ")}`);
        setInterpreted(null);
        queryClient.invalidateQueries({ queryKey: ["scarlets"] });
      }
    } finally {
      setDeploying(false);
    }
  };

  const entries = interpreted ? Object.entries(interpreted) : [];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Interpret</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label htmlFor="file">Upload a script</Label>
            <input
              id="file"
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm text-gray-600 file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-1.5 file:text-sm file:font-medium"
            />
            <p className="mt-1 text-xs text-gray-400">
              Scans the uploaded file for <code>#scarlet</code> declaration comments - works
              from any machine, not just wherever composer-api itself runs.
            </p>
            <Button onClick={handleInterpretUpload} disabled={interpreting || !file} className="mt-2">
              {interpreting ? "Interpreting…" : "Upload & Interpret"}
            </Button>
          </div>

          <div className="flex items-center gap-3 text-xs text-gray-400">
            <div className="h-px flex-1 bg-border" />
            or
            <div className="h-px flex-1 bg-border" />
          </div>

          <div>
            <Label htmlFor="path">Script or directory path</Label>
            <Input
              id="path"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="/path/on/composer-api's/own/filesystem"
              className="mt-1"
            />
            <p className="mt-1 text-xs text-gray-400">
              Scans for <code>#scarlet</code> declaration comments - a path on the machine
              composer-api itself runs on, not your browser. Use this for a whole directory;
              a single file is usually easier to just upload above.
            </p>
            <Button onClick={handleInterpretPath} disabled={interpreting || !path} className="mt-2">
              {interpreting ? "Interpreting…" : "Interpret"}
            </Button>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}
        </CardContent>
      </Card>

      {entries.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Preview ({entries.length})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {entries.map(([name, entry]) => (
              <div key={name} className="rounded-md border p-3 space-y-2">
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-mono font-medium">{name}</span>
                  <span className="text-xs text-gray-400">{entry.scarlet_type}</span>
                  <span className="text-xs text-gray-400">mode={String(entry.scarlet_attributes?.mode ?? "")}</span>
                </div>
                <textarea
                  className="w-full min-h-20 rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  value={entry.description}
                  onChange={(e) => updateDescription(name, e.target.value)}
                  placeholder="Description"
                />
              </div>
            ))}
            <div className="flex items-center gap-3">
              <Button onClick={handleDeploy} disabled={deploying}>
                {deploying ? "Deploying…" : "Deploy Scarlets"}
              </Button>
              {deployMessage && <span className="text-xs text-muted-foreground">{deployMessage}</span>}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function ScarletsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Scarlets</h1>
      <Tabs defaultValue="view">
        <TabsList>
          <TabsTrigger value="view">View Scarlets</TabsTrigger>
          <TabsTrigger value="deploy">Deploy Scarlets</TabsTrigger>
        </TabsList>
        <TabsContent value="view">
          <ViewTab />
        </TabsContent>
        <TabsContent value="deploy">
          <DeployTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
