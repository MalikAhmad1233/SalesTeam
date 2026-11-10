"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { api } from "@/lib/api";
import { can, type Me } from "@/lib/session";

interface NavItem {
  href: string;
  label: string;
  permission?: string;
  /** Future module: shown greyed out with the phase it arrives in. */
  phase?: string;
}

const NAV: { group: string; items: NavItem[] }[] = [
  { group: "", items: [{ href: "/overview", label: "Overview" }] },
  {
    group: "Work",
    items: [
      { href: "/conversations", label: "Conversations", phase: "Phase 3" },
      { href: "/leads", label: "Leads", permission: "leads.read" },
      { href: "/customers", label: "Customers", permission: "crm.accounts.read" },
      { href: "/pipeline", label: "Sales Pipeline", permission: "crm.accounts.read" },
      { href: "/tasks", label: "Tasks & Follow-ups", permission: "crm.tasks.manage" },
      { href: "/quotations", label: "Quotations", phase: "Phase 2" },
    ],
  },
  {
    group: "Delivery",
    items: [
      { href: "/tutors", label: "Tutors", phase: "Phase 5" },
      { href: "/scheduling", label: "Scheduling", phase: "Phase 5" },
    ],
  },
  {
    group: "Revenue",
    items: [
      { href: "/pricing", label: "Pricing", phase: "Phase 2" },
      { href: "/payments", label: "Payments", phase: "Phase 6" },
      { href: "/retention", label: "Retention", phase: "Phase 7" },
    ],
  },
  {
    group: "Intelligence",
    items: [
      { href: "/agents", label: "AI Agents", phase: "Phase 4" },
      { href: "/reports", label: "Reports", phase: "Phase 8" },
    ],
  },
  {
    group: "Admin",
    items: [
      { href: "/team", label: "Team", permission: "users.read" },
      { href: "/integrations", label: "Integrations", phase: "Phase 3" },
      { href: "/settings", label: "Settings", permission: "settings.read" },
    ],
  },
];

export function AppShell({ me, children }: { me: Me; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();

  async function signOut() {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      queryClient.clear();
      router.replace("/login");
    }
  }

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 border-r border-border bg-surface md:block">
        <div className="px-5 py-5">
          <p className="text-lg font-semibold text-primary">Mixt AI</p>
          <p className="text-xs text-muted">Mixt Academy</p>
        </div>
        <nav aria-label="Main" className="px-3 pb-6">
          {NAV.map(({ group, items }) => {
            const visible = items.filter((i) => i.phase || !i.permission || can(me, i.permission));
            if (visible.length === 0) return null;
            return (
              <div key={group || "home"} className="mb-4">
                {group ? <p className="px-2 pb-1 text-xs font-semibold uppercase tracking-wide text-muted">{group}</p> : null}
                <ul>
                  {visible.map((item) =>
                    item.phase ? (
                      <li key={item.href}>
                        <span
                          className="flex items-center justify-between rounded-md px-2 py-1.5 text-sm text-muted/70"
                          title={`Arrives in ${item.phase}`}
                          aria-disabled="true"
                        >
                          {item.label}
                          <span className="text-[10px] uppercase">{item.phase}</span>
                        </span>
                      </li>
                    ) : (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          aria-current={pathname.startsWith(item.href) ? "page" : undefined}
                          className={`block rounded-md px-2 py-1.5 text-sm ${
                            pathname.startsWith(item.href)
                              ? "bg-primary-soft font-medium text-primary-strong"
                              : "text-ink hover:bg-white"
                          }`}
                        >
                          {item.label}
                        </Link>
                      </li>
                    ),
                  )}
                </ul>
              </div>
            );
          })}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-border px-4 py-3 md:px-6">
          <nav aria-label="Mobile" className="flex gap-3 overflow-x-auto text-sm md:hidden">
            {["/overview", "/leads", "/customers", "/pipeline", "/tasks"].map((href) => (
              <Link key={href} href={href} className="whitespace-nowrap text-accent">
                {href.slice(1)}
              </Link>
            ))}
          </nav>
          <span className="hidden text-sm text-muted md:block">Times shown in {me.timezone}</span>
          <div className="flex items-center gap-3">
            <span className="text-sm text-ink" data-testid="current-user">
              {me.full_name}
            </span>
            <button type="button" onClick={signOut} className="text-sm text-accent hover:underline">
              Sign out
            </button>
          </div>
        </header>
        <main className="flex-1 px-4 py-6 md:px-8">{children}</main>
      </div>
    </div>
  );
}
