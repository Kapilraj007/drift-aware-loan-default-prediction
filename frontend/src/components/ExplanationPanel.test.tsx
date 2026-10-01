import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExplanationPanel } from "./ExplanationPanel";

describe("ExplanationPanel", () => {
  it("renders no more than five signed, accessible contributors", () => {
    render(
      <ExplanationPanel
        explanation={{
          available: true,
          narrative: "A readable explanation.",
          top_features: Array.from({ length: 6 }, (_, index) => ({
            feature: `feature_${index}`,
            display_name: `Feature ${index + 1}`,
            contribution: index % 2 === 0 ? 0.1 + index / 100 : -0.1 - index / 100,
            direction: index % 2 === 0 ? "risk_increasing" : "risk_reducing",
            feature_value: index,
          })),
        }}
      />,
    );

    expect(screen.getByRole("list", { name: /top feature contributions/i })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByText("Feature 5")).toBeInTheDocument();
    expect(screen.queryByText("Feature 6")).not.toBeInTheDocument();
  });
});
