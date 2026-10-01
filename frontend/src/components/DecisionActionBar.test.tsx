import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PredictionResponse } from "../types";

const mocks = vi.hoisted(() => ({
  submitFeedback: vi.fn().mockResolvedValue({
    id: "feedback-1",
    prediction_id: "prediction-1",
    officer_id: "officer-1",
    decision: "escalate",
    agreed_with_model: true,
    note: "Verify income",
    detector_state: {
      status: "stable", score_stream_count: 1, latest_score: 0.72, adwin_change_detected: false,
      feature_drift_count: 0, updated_at: "2026-01-01T00:00:00Z", feature_results: [],
    },
    created_at: "2026-01-01T00:00:00Z",
  }),
}));

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {},
  apiClient: mocks,
}));

import { DecisionActionBar } from "./DecisionActionBar";

const prediction: PredictionResponse = {
  id: "prediction-1",
  application_id: "application-1",
  model_version: "v1",
  score: 0.72,
  threshold: 0.5,
  risk_flag: true,
  explanation: { available: true, narrative: "Narrative", top_features: [] },
  detector_state: {
    status: "stable", score_stream_count: 1, latest_score: 0.72, adwin_change_detected: false,
    feature_drift_count: 0, updated_at: "2026-01-01T00:00:00Z", feature_results: [],
  },
  created_at: "2026-01-01T00:00:00Z",
};

describe("DecisionActionBar", () => {
  it("records an officer escalation with agreement and note", async () => {
    render(<DecisionActionBar prediction={prediction} />);

    fireEvent.change(screen.getByLabelText(/relationship to model/i), { target: { value: "agree" } });
    fireEvent.change(screen.getByLabelText(/decision note/i), { target: { value: "Verify income" } });
    fireEvent.click(screen.getByRole("button", { name: "Escalate" }));

    await waitFor(() => expect(mocks.submitFeedback).toHaveBeenCalledWith("prediction-1", "escalate", true, "Verify income"));
    expect(await screen.findByText(/escalate recorded/i)).toBeInTheDocument();
  });
});
