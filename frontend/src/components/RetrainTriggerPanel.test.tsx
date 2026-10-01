import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  retrainingTickets: vi.fn().mockResolvedValue([]),
  createRetrainingTicket: vi.fn().mockResolvedValue({
    id: "ticket-1", monitoring_snapshot_id: "snapshot-1", requested_by_id: "analyst-1", reason: "Sustained KS drift", human_review_confirmed: true,
    status: "open", reviewed_by_id: null, review_note: null, created_at: "2026-01-01T00:00:00Z", reviewed_at: null,
  }),
}));

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {},
  apiClient: mocks,
}));

import { RetrainTriggerPanel } from "./RetrainTriggerPanel";

describe("RetrainTriggerPanel", () => {
  it("requires human confirmation and creates a review ticket without auto-retraining", async () => {
    render(
      <RetrainTriggerPanel
        status={{
          status: "drift_detected", score_stream_count: 12, latest_score: 0.6, adwin_change_detected: false,
          feature_drift_count: 1, updated_at: "2026-01-01T00:00:00Z", feature_results: [],
        }}
      />,
    );

    fireEvent.change(screen.getByLabelText(/review rationale/i), { target: { value: "Sustained KS drift" } });
    const button = screen.getByRole("button", { name: /open retraining review ticket/i });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(button);

    await waitFor(() => expect(mocks.createRetrainingTicket).toHaveBeenCalledWith("Sustained KS drift"));
    expect(await screen.findByText("Sustained KS drift")).toBeInTheDocument();
  });
});
