import type { ExplanationAssignment, ExplanationVariant } from "../types";

export function explanationVisible(assignment: ExplanationAssignment | null): boolean {
  return assignment?.variant === "explanation_shown";
}

export function ABToggle({ assignment }: { assignment: ExplanationAssignment | null }) {
  const variant: ExplanationVariant | null = assignment?.variant ?? null;
  const visible = variant === "explanation_shown";
  return (
    <div className="experiment-state" data-variant={variant ?? "loading"} aria-live="polite">
      <span className="experiment-label">Explanation study arm</span>
      <span className={visible ? "experiment-visible" : "experiment-hidden"}>
        {variant === null
          ? "Assigning…"
          : visible
            ? "Score with explanation"
            : "Score only"}
      </span>
    </div>
  );
}
