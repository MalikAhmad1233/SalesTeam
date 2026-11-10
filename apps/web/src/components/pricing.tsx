"use client";

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

