import type { CheckStatus } from "../types";
import { Check, X } from "lucide-react";

export function StatusBadge({ status }: { status: CheckStatus | string }) {
  const label = status
    .replace(/([A-Z])/g, " $1")
    .replace(/^./, (character) => character.toUpperCase());
  const positive = new Set([
    "found",
    "readyForPackaging",
    "packaged",
    "matched",
    "exactMatch",
    "confirmed",
    "complete",
    "success",
    "loop"
  ]).has(status);
  const Icon = positive ? Check : X;
  return (
    <span
      className={`status status-${status} ${positive ? "status-positive" : "status-negative"}`}
      role="img"
      aria-label={label}
      title={label}
    >
      <Icon size={15} strokeWidth={2.4} aria-hidden="true" />
    </span>
  );
}
