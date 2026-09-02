"use client";
import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useAuth } from "@/lib/context/AuthContext";
import { deleteDataSource, updateDataSource } from "@/lib/api/data-sources";
import type { DataSource } from "@/lib/types";

const toCsv = (values: string[]) => values.join(", ");
const fromCsv = (value: string) =>
  value.split(",").map((s) => s.trim()).filter(Boolean);

// Mirrors ScarletCard.tsx's expand/edit/delete shape. Registration here is
// policy + directory only - editing a data source never touches any
// credential (none exists on this entry at all, see composer-api/
// data_sources_store.py's docstring); the broker at broker_url holds its
// own data-source credential entirely on its own.
export function DataSourceCard({ dataSource }: { dataSource: DataSource }) {
  const { isAdmin } = useAuth();
  const [expanded, setExpanded] = useState(false);
  const [description, setDescription] = useState(dataSource.description);
  const [brokerUrl, setBrokerUrl] = useState(dataSource.broker_url);
  const [allowedUsers, setAllowedUsers] = useState(toCsv(dataSource.allowed_users));
  const [allowedGroups, setAllowedGroups] = useState(toCsv(dataSource.allowed_groups));
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const res = await updateDataSource(dataSource.name, {
        description,
        broker_url: brokerUrl,
        allowed_users: fromCsv(allowedUsers),
        allowed_groups: fromCsv(allowedGroups),
      });
      setMessage(res.error ? `Failed: ${res.response}` : "Saved.");
      queryClient.invalidateQueries({ queryKey: ["data-sources"] });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    await deleteDataSource(dataSource.name);
    setConfirmDelete(false);
    queryClient.invalidateQueries({ queryKey: ["data-sources"] });
  };

  return (
    <>
      <AlertDialog open={confirmDelete} onOpenChange={(open) => !open && setConfirmDelete(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove data source?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to remove &quot;{dataSource.name}&quot; from the registry? Any
              broker still deployed against this name will start rejecting every authorize check.
              This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleDelete}
            >
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Card>
        <CardHeader className="cursor-pointer py-3" onClick={() => setExpanded(!expanded)}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CardTitle className="text-sm font-medium font-mono">{dataSource.name}</CardTitle>
              <Badge variant="outline" className="text-xs">{dataSource.type}</Badge>
            </div>
            <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
              {isAdmin && (
                <Button size="sm" variant="destructive" onClick={() => setConfirmDelete(true)}>Remove</Button>
              )}
              {expanded ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
            </div>
          </div>
        </CardHeader>

        {expanded && (
          <CardContent className="pt-0 space-y-3 border-t">
            <div className="pt-3 space-y-3 text-sm">
              <div>
                <Label htmlFor={`broker-url-${dataSource.name}`}>Broker URL</Label>
                <Input
                  id={`broker-url-${dataSource.name}`}
                  value={brokerUrl}
                  onChange={(e) => setBrokerUrl(e.target.value)}
                  disabled={!isAdmin}
                  className="mt-1 font-mono text-xs"
                />
              </div>
              <div>
                <Label htmlFor={`description-${dataSource.name}`}>Description</Label>
                <textarea
                  id={`description-${dataSource.name}`}
                  className="mt-1 w-full min-h-16 rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  disabled={!isAdmin}
                  placeholder="What this data source is, and what an agent should expect from it - fed into agent context."
                />
              </div>
              <div>
                <Label htmlFor={`allowed-users-${dataSource.name}`}>Allowed users (comma-separated)</Label>
                <Input
                  id={`allowed-users-${dataSource.name}`}
                  value={allowedUsers}
                  onChange={(e) => setAllowedUsers(e.target.value)}
                  disabled={!isAdmin}
                  className="mt-1"
                />
              </div>
              <div>
                <Label htmlFor={`allowed-groups-${dataSource.name}`}>Allowed Nebula groups (comma-separated)</Label>
                <Input
                  id={`allowed-groups-${dataSource.name}`}
                  value={allowedGroups}
                  onChange={(e) => setAllowedGroups(e.target.value)}
                  disabled={!isAdmin}
                  className="mt-1"
                />
                <p className="mt-1 text-xs text-gray-400">
                  Any agent presenting a Nebula identity in one of these groups (or one of the users
                  above) is authorized - checked by the broker against composer-api on every query.
                </p>
              </div>
              {isAdmin && (
                <div className="flex items-center gap-3">
                  <Button size="sm" onClick={handleSave} disabled={saving}>
                    {saving ? "Saving…" : "Save"}
                  </Button>
                  {message && <span className="text-xs text-muted-foreground">{message}</span>}
                </div>
              )}
            </div>
          </CardContent>
        )}
      </Card>
    </>
  );
}
