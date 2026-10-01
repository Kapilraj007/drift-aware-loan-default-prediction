import { useState } from "react";
import { ApiError, apiClient } from "../api/client";
import type { FeedbackResponse, OfficerDecision, PredictionResponse } from "../types";
import { StatusBadge } from "./StatusBadge";

export function DecisionActionBar({ prediction }: { prediction: PredictionResponse }) {
  const [agreement, setAgreement] = useState<"agree" | "override" | "unsure">("unsure");
  const [note, setNote] = useState("");
  const [feedback, setFeedback] = useState<FeedbackResponse | null>(null);
  const [pendingDecision, setPendingDecision] = useState<OfficerDecision | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function recordDecision(decision: OfficerDecision) {
    setPendingDecision(decision);
    setError(null);
    try {
      const saved = await apiClient.submitFeedback(
        prediction.id,
        decision,
        agreement === "unsure" ? null : agreement === "agree",
        note.trim() || null,
      );
      setFeedback(saved);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.detail : "The decision could not be saved.");
    } finally {
      setPendingDecision(null);
    }
  }

  return (
    <section className="panel decision-panel" aria-labelledby="decision-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Step 4</p>
          <h2 id="decision-title">Officer decision</h2>
        </div>
        {feedback ? <StatusBadge status={feedback.detector_state.status} /> : null}
      </div>
      <p>
        Record the human decision and whether it agrees with the displayed model score. This action is auditable and does not trigger automatic lending or retraining.
      </p>
      <div className="decision-form">
        <div className="field">
          <label htmlFor="agreement">Relationship to model score</label>
          <select
            id="agreement"
            value={agreement}
            onChange={(event) => setAgreement(event.target.value as typeof agreement)}
          >
            <option value="unsure">Not recorded</option>
            <option value="agree">Agree with score assessment</option>
            <option value="override">Override score assessment</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="decision-note">Decision note</label>
          <textarea
            id="decision-note"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={4000}
            rows={3}
            placeholder="Optional context for the review record"
          />
        </div>
      </div>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="decision-actions" aria-label="Record officer decision">
        {(["approve", "decline", "escalate"] as const).map((decision) => (
          <button
            type="button"
            className={`button decision-${decision}`}
            key={decision}
            disabled={pendingDecision !== null}
            onClick={() => void recordDecision(decision)}
          >
            {pendingDecision === decision ? "Recording…" : decision[0].toUpperCase() + decision.slice(1)}
          </button>
        ))}
      </div>
      {feedback ? (
        <p className="feedback-confirmation" role="status">
          {feedback.decision[0].toUpperCase() + feedback.decision.slice(1)} recorded at{" "}
          {new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(feedback.created_at))}. Detector state: {" "}
          <StatusBadge status={feedback.detector_state.status} />
        </p>
      ) : null}
    </section>
  );
}
