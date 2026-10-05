import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  applicationSchema: vi.fn().mockResolvedValue({
    fields: [
      { name: "annual_inc", label: "Annual income from API", type: "number", kind: "number", group: "Applicant & finances", required: false, nullable: true },
      { name: "loan_amnt", label: "Requested loan from API", type: "number", kind: "number", group: "Loan details", required: false, nullable: true },
      { name: "issue_d", label: "Issue month from API", type: "month", kind: "month", group: "Loan details", required: true, nullable: false },
      { name: "open_acc", label: "Open accounts from API", type: "number", kind: "number", group: "Credit history", required: false, nullable: true },
    ],
  }),
  createApplication: vi.fn(),
  createPrediction: vi.fn(),
}));

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {},
  apiClient: mocks,
}));

import { NewApplicationPage } from "./ApplicationPages";

describe("NewApplicationPage", () => {
  it("builds its four-step wizard from server field metadata", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><NewApplicationPage /></MemoryRouter>
        </QueryClientProvider>
      </AntApp>,
    );

    expect(await screen.findByLabelText("Annual income from API")).toBeInTheDocument();
    expect(mocks.applicationSchema).toHaveBeenCalledOnce();
    expect(screen.getByText("Applicant & finances")).toBeInTheDocument();
    expect(screen.getByText("Loan details")).toBeInTheDocument();
    expect(screen.getByText("Credit history")).toBeInTheDocument();
    expect(screen.getByText("Review & submit")).toBeInTheDocument();
  });
});
