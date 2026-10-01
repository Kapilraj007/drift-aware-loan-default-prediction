import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ABToggle, explanationVisible } from "./ABToggle";

describe("ABToggle", () => {
  it("uses the durable assignment to control explanation visibility", () => {
    const assignment = { id: "a-1", variant: "score_only" as const, created_at: "2026-01-01T00:00:00Z" };
    expect(explanationVisible(assignment)).toBe(false);
    render(<ABToggle assignment={assignment} />);
    expect(screen.getByText("Score only")).toBeInTheDocument();
  });
});
