import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  createApplication: vi.fn().mockResolvedValue({ id: "application-1" }),
  createPrediction: vi.fn().mockResolvedValue({ id: "prediction-1" }),
}));

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {},
  apiClient: mocks,
}));

import { ApplicationUploadForm } from "./ApplicationUploadForm";

describe("ApplicationUploadForm", () => {
  it("persists an application before requesting a prediction", async () => {
    const onPrediction = vi.fn();
    render(<ApplicationUploadForm onPrediction={onPrediction} />);

    fireEvent.change(screen.getByLabelText(/application month/i), { target: { value: "Jan-2018" } });
    fireEvent.click(screen.getByRole("button", { name: /save and score/i }));

    await waitFor(() => expect(mocks.createApplication).toHaveBeenCalledTimes(1));
    expect(mocks.createPrediction).toHaveBeenCalledWith("application-1");
    expect(onPrediction).toHaveBeenCalledWith({ id: "prediction-1" });
  });
});
