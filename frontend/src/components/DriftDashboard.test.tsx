import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const status = {
    status: "stable",
    score_stream_count: 4,
    latest_score: 0.55,
    adwin_change_detected: false,
    feature_drift_count: 0,
    updated_at: "2026-01-01T00:00:00Z",
    feature_results: [{ feature: "dti", statistic: 0.12, p_value: 0.5, drift_detected: false, reference_count: 3, current_count: 3 }],
  };
  return {
    status,
    monitoringStatus: vi.fn().mockResolvedValue(status),
    monitoringHistory: vi.fn().mockResolvedValue({
      snapshots: [{ id: "snapshot-1", source: "feature_drift", snapshot: status, created_at: "2026-01-01T00:00:00Z" }],
    }),
    evaluateFeatureDrift: vi.fn(),
  };
});

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {},
  apiClient: mocks,
}));

import { DriftDashboard } from "./DriftDashboard";

describe("DriftDashboard", () => {
  it("shows status, the latest KS result, and trend chart", async () => {
    const onStatusChange = vi.fn();
    const view = render(<DriftDashboard onStatusChange={onStatusChange} />);

    expect(await screen.findByText("Stable")).toBeInTheDocument();
    expect(screen.getAllByText("dti")).toHaveLength(2);
    expect(screen.getByRole("img", { name: /feature ks statistic trends/i })).toBeInTheDocument();
    await waitFor(() => expect(onStatusChange).toHaveBeenCalledWith(mocks.status));
    view.unmount();
  });
});
