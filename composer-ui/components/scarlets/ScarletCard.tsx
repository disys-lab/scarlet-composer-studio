"use client";
import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { deleteScarlet, resetScarlet, updateScarletDescription } from "@/lib/api/scarlets";
import type { Scarlet } from "@/lib/types";

// Mirrors gustavo-ui's AppExpander.tsx pattern: Card header toggles expand,
// AlertDialog for the destructive action. Replaces
// scarletcomposer/Scarlets.py's per-scarlet st.expander block - including
// its *working* per-row "Update Description" button (writes directly via
// Redis). The page-level "Update Description" button that called a
// nonexistent ScarletHandler.updateScarletsDescription() method isn't
// replicated - see composer-api/routers/scarlets.py's docstring.
export function ScarletCard({ scarlet }: { scarlet: Scarlet }) {
  const [expanded, setExpanded] = useState(false);
  const [description, setDescription] = useState(scarlet.description);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleSaveDescription = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const res = await updateScarletDescription(scarlet.name, description);
      setMessage(res.error ? `Failed: ${res.response}` : "Description updated.");
      queryClient.invalidateQueries({ queryKey: ["scarlets"] });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    await deleteScarlet(scarlet.name);
    setConfirmDelete(false);
    queryClient.invalidateQueries({ queryKey: ["scarlets"] });
  };

  const handleReset = async () => {
    const res = await resetScarlet(scarlet.name);
    setConfirmReset(false);
    setMessage(res.error ? `Reset failed: ${res.response}` : "Scarlet data cleared.");
  };

  return (
    <>
      <AlertDialog open={confirmDelete} onOpenChange={(open) => !open && setConfirmDelete(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete scarlet definition?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete &quot;{scarlet.name}&quot;? This removes its definition
              from Redis. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleDelete}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirmReset} onOpenChange={(open) => !open && setConfirmReset(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reset scarlet data?</AlertDialogTitle>
            <AlertDialogDescription>
              This clears the data stored under &quot;{scarlet.name}&quot; (not its definition). This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleReset}
            >
              Reset
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Card>
        <CardHeader className="cursor-pointer py-3" onClick={() => setExpanded(!expanded)}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CardTitle className="text-sm font-medium font-mono">{scarlet.name}</CardTitle>
              <Badge variant="outline" className="text-xs">{scarlet.scarlet_type}</Badge>
              {scarlet.mode && <Badge variant="secondary" className="text-xs">{scarlet.mode}</Badge>}
            </div>
            <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
              <Button size="sm" variant="ghost" onClick={() => setConfirmReset(true)}>Reset</Button>
              <Button size="sm" variant="destructive" onClick={() => setConfirmDelete(true)}>Delete</Button>
              {expanded ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
            </div>
          </div>
        </CardHeader>

        {expanded && (
          <CardContent className="pt-0 space-y-3 border-t">
            <div className="pt-3 space-y-2 text-sm">
              {scarlet.created_by && (
                <div className="flex gap-2">
                  <span className="text-muted-foreground w-24 shrink-0">Created by</span>
                  <span className="font-mono text-xs">{scarlet.created_by}</span>
                </div>
              )}
              <textarea
                className="w-full min-h-24 rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Description - data format, key naming, usage intent. Fed directly into agent context windows."
              />
              <div className="flex items-center gap-3">
                <Button size="sm" onClick={handleSaveDescription} disabled={saving}>
                  {saving ? "Saving…" : "Update Description"}
                </Button>
                {message && <span className="text-xs text-muted-foreground">{message}</span>}
              </div>
            </div>
          </CardContent>
        )}
      </Card>
    </>
  );
}
