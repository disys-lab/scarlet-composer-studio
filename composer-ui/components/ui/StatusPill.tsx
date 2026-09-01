// Ported from gustavo-ui's StatusPill.tsx. Extended with composer's own
// agent-health vocabulary (online/stale/unknown, from composer-api's
// status.py) alongside gustavo's original Up/Down/Unknown, rather than
// forcing a translation layer at every call site - both sets of keys are
// valid inputs to the same component.
type Status = "Up" | "Down" | "Unknown" | "online" | "stale" | string;

const VARIANT_MAP: Record<string, string> = {
  Up: "bg-green-100 text-green-800 border-green-200",
  Down: "bg-red-100 text-red-800 border-red-200",
  Unknown: "bg-yellow-100 text-yellow-800 border-yellow-200",
  online: "bg-green-100 text-green-800 border-green-200",
  stale: "bg-red-100 text-red-800 border-red-200",
  unknown: "bg-yellow-100 text-yellow-800 border-yellow-200",
};

const PULSE_STATUSES = new Set(["Up", "online"]);

export function StatusPill({ status }: { status: Status }) {
  const cls = VARIANT_MAP[status] ?? VARIANT_MAP.Unknown;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${cls}`}
    >
      {PULSE_STATUSES.has(status) && (
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-500 opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-green-600" />
        </span>
      )}
      {status}
    </span>
  );
}
