import type { DetectorStatus } from "../types";

const statusCopy: Record<string, { label: string; className: string }> = {
  stable: { label: "Stable", className: "status-stable" },
  watch: { label: "Watch", className: "status-watch" },
  not_observed: { label: "Watch", className: "status-watch" },
  drift_detected: { label: "Drift detected", className: "status-drift" },
};

export function StatusBadge({ status }: { status: DetectorStatus }) {
  const presentation = statusCopy[status] ?? { label: status.replaceAll("_", " "), className: "status-watch" };
  return <span className={`status-badge ${presentation.className}`}>{presentation.label}</span>;
}
