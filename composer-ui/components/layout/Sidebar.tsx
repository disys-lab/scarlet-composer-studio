"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Users, Database, FileText, Container, Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";

// Ported from gustavo-ui/components/layout/Sidebar.tsx - same shell,
// same nav-array-mapped-to-Link pattern, same active-state logic. No
// user/role block below the nav - composer has no auth system today,
// unlike Gustavo.
const NAV = [
  { href: "/dashboard",        label: "Dashboard",        icon: LayoutDashboard },
  { href: "/agents",           label: "Agents",           icon: Users },
  { href: "/scarlets",         label: "Scarlets",         icon: Database },
  { href: "/data-sources",     label: "Data Sources",     icon: Database },
  { href: "/logging",          label: "Logging",          icon: FileText },
  { href: "/container-builds", label: "Container Builds", icon: Container },
  { href: "/settings",         label: "Settings",         icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex flex-col w-56 min-h-screen bg-white border-r border-gray-200 px-3 py-5 shrink-0">
      <div className="flex flex-col items-center gap-1 mb-7 px-2">
        <span className="text-lg font-semibold text-gray-900">Scarlet Composer</span>
      </div>

      <nav className="flex flex-col gap-0.5 flex-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const isActive = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-gray-100 text-gray-900"
                  : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="flex-1">{label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
