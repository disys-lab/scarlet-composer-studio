"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getDashboardStats } from "@/lib/api/dashboard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/StatusPill";

// Same stat-card grid pattern as gustavo-ui's dashboard, scoped to data
// that actually exists for composer - no fabricated "platform services"
// card (composer doesn't manage services the way Gustavo does).
export default function DashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: getDashboardStats,
    refetchInterval: 30_000,
    staleTime: 25_000,
  });

  const stats = data && !data.error ? data.response : undefined;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Redis Connection</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-6 w-24" />
          ) : (
            <StatusPill status={stats?.redis_ok ? "Up" : "Down"} />
          )}
          {stats && !stats.redis_ok && stats.redis_error && (
            <p className="mt-2 text-sm text-red-600">{stats.redis_error}</p>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Agents Online</CardTitle>
              <Link href="/agents" className="text-xs text-blue-600 hover:underline">
                View →
              </Link>
            </div>
          </CardHeader>
          <CardContent className="flex items-center justify-center h-24">
            {isLoading || !stats ? (
              <Skeleton className="h-12 w-20" />
            ) : (
              <div className="text-center">
                <p className="text-4xl font-bold text-gray-900">{stats.agent_count}</p>
                <p className="text-sm text-gray-500 mt-1">on bus &quot;{stats.agent_bus}&quot;</p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Scarlet Definitions</CardTitle>
              <Link href="/scarlets" className="text-xs text-blue-600 hover:underline">
                Manage →
              </Link>
            </div>
          </CardHeader>
          <CardContent className="flex items-center justify-center h-24">
            {isLoading || !stats ? (
              <Skeleton className="h-12 w-20" />
            ) : (
              <div className="text-center">
                <p className="text-4xl font-bold text-gray-900">{stats.scarlet_count}</p>
                <p className="text-sm text-gray-500 mt-1">
                  {stats.scarlet_count === 1 ? "definition registered" : "definitions registered"}
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
