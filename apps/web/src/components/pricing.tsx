"use client";

import Link from "next/link";
import type { Schemas } from "@/lib/api";

export function PricingBanners({ status }: { status?: Schemas["PricingStatusOut"] }) {
  if (!status) return null;
  return (
    <div className="mb-6 space-y-2">
      {!status.catalogue_complete ? (
        <p role="note" className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-warning">
          <strong>Pricing catalogue incomplete.</strong> More pricing sheets are still being collected (BD-017).
        </p>
      ) : null}
      {status.active_versions === 0 ? (
        <p role="note" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-danger">
          <strong>No pricing is active.</strong> Nothing here may be quoted to a customer until it passes the activation checklist.
          Figures are shown exactly as supplied.
        </p>
      ) : null}
    </div>
  );
}

export function statusTone(status: string): "neutral" | "success" | "warning" | "danger" | "accent" {
  if (status === "active") return "success";
  if (status === "approved" || status === "in_review") return "accent";
  if (status === "rejected" || status === "retired") return "danger";
  return "warning";
}


const TABS = [
  { href: "/pricing", label: "Price books", permission: "pricing.read" },
  { href: "/pricing/import", label: "Import sheet", permission: "pricing.import" },
  { href: "/pricing/rules", label: "Rules", permission: "pricing.read" },
  { href: "/pricing/promotions", label: "Promotions", permission: "pricing.read" },
];

export function PricingTabs({ current, permissions }: { current: string; permissions: string[] }) {
  return (
    <nav aria-label="Pricing sections" className="mb-6 flex flex-wrap gap-2 border-b border-border pb-2 text-sm">
      {TABS.filter((t) => permissions.includes(t.permission)).map((t) => (
        <Link
          key={t.href}
          href={t.href}
          aria-current={current === t.href ? "page" : undefined}
          className={`rounded-md px-3 py-1.5 ${current === t.href ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-ink"}`}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
