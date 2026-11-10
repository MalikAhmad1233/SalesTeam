// Display helpers. Money always shows its currency code; times show the viewer's zone.

export function formatMoney(amountMinor: number, currency: string, minorUnits: number): string {
  const major = amountMinor / 10 ** minorUnits;
  const number = new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: amountMinor % 10 ** minorUnits === 0 ? 0 : minorUnits,
    maximumFractionDigits: minorUnits,
  }).format(major);
  return `${currency} ${number}`;
}

export function formatDateTime(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timeZone || undefined,
  }).format(new Date(iso));
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = iso.length === 10 ? new Date(`${iso}T00:00:00Z`) : new Date(iso);
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" }).format(date);
}

/** Current local time in a customer's zone, e.g. "16:05 Asia/Dubai". */
export function localTimeIn(timeZone: string | null | undefined): string | null {
  if (!timeZone) return null;
  try {
    const time = new Intl.DateTimeFormat("en-GB", { timeStyle: "short", timeZone }).format(new Date());
    return `${time} ${timeZone}`;
  } catch {
    return null;
  }
}

export function humanize(code: string | null | undefined): string {
  if (!code) return "—";
  return code.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
