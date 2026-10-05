import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  applicationReview: vi.fn(),
  createPrediction: vi.fn(),
  submitFeedback: vi.fn(),
  recordExplanationExposure: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {},
  apiClient: mocks,
}));
vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    hasPermission: (permission: string) => ["prediction:create", "feedback:create", "experiment:participate"].includes(permission),
  }),
}));

import { ApplicationReviewPage } from "./ApplicationReviewPage";

function reviewResponse(explanationAvailable: boolean) {
  return {
    application: {
      id: "application-1",
      external_reference: "CASE-001",
      features: { annual_inc: 75_000, issue_d: "Jan-2018" },
      created_by_id: "officer-1",
      created_at: "2026-01-01T00:00:00Z",
    },
    latest_prediction: {
      id: "prediction-1",
      application_id: "application-1",
      model_version: "demo-model",
      score: 0.72,
      threshold: 0.5,
      risk_flag: true,
      study_variant: explanationAvailable ? "explanation_shown" : "score_only",
      explanation: explanationAvailable ? {
        available: true,
        narrative: "Income and DTI were the strongest contributors.",
        top_features: [{
          feature: "dti",
          display_name: "Debt to income",
          contribution: 0.3,
          direction: "risk_increasing",
          feature_value: 31,
        }],
      } : {
        available: false,
        narrative: "Explanation withheld.",
        top_features: [],
      },
      detector_state: {
        status: "stable",
        score_stream_count: 1,
        latest_score: 0.72,
        adwin_change_detected: false,
        feature_drift_count: 0,
        updated_at: "2026-01-01T00:00:00Z",
        feature_results: [],
      },
      created_at: "2026-01-01T00:01:00Z",
    },
    feedback_history: [],
    current_feedback: null,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <AntApp>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/applications/application-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routes>
            <Route path="/applications/:applicationId" element={<ApplicationReviewPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </AntApp>,
  );
}

describe("ApplicationReviewPage study arms", () => {
  beforeEach(() => {
    mocks.applicationReview.mockReset();
    mocks.recordExplanationExposure.mockClear();
  });

  it("shows contributors only when the API marks the explanation available", async () => {
    mocks.applicationReview.mockResolvedValue(reviewResponse(true));
    renderPage();

    expect(await screen.findByText("Income and DTI were the strongest contributors.")).toBeInTheDocument();
    expect(screen.getByText(/Debt to income/)).toBeInTheDocument();
    await waitFor(() => expect(mocks.recordExplanationExposure).toHaveBeenCalledWith("prediction-1"));
  });

  it("shows the score-only notice without rendering contributor data", async () => {
    mocks.applicationReview.mockResolvedValue(reviewResponse(false));
    renderPage();

    expect(await screen.findByText("Explanation not included in this study view")).toBeInTheDocument();
    expect(screen.queryByText("Debt to income")).not.toBeInTheDocument();
  });
});
