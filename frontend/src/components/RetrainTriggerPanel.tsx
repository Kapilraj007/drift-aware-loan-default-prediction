import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, apiClient } from "../api/client";
import type { DriftStatus, RetrainingTicket } from "../types";
import { StatusBadge } from "./StatusBadge";

export function RetrainTriggerPanel({ status }: { status: DriftStatus | null }) {
  const [tickets, setTickets] = useState<RetrainingTicket[]>([]);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshTickets() {
    try {
      const response = await apiClient.retrainingTickets();
      setTickets(response);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.detail : "Retraining tickets could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshTickets();
  }, []);

  async function createTicket(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmed) {
      setError("Confirm human review before opening a retraining ticket.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const ticket = await apiClient.createRetrainingTicket(reason.trim());
      setTickets((current) => [ticket, ...current]);
      setReason("");
      setConfirmed(false);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.detail : "The retraining ticket could not be created.");
    } finally {
      setSubmitting(false);
    }
  }

  const driftDetected = status?.status === "drift_detected";
  return (
    <section className="panel retrain-panel" aria-labelledby="retrain-title">
      <p className="eyebrow">Human gate</p>
      <h2 id="retrain-title">Retraining review</h2>
      <p>
        A ticket captures a request for human review of sustained drift. It never queues a model job, changes a threshold, or deploys a model automatically.
      </p>
      {status ? (
        <p>
          Current detector state: <StatusBadge status={status.status} />
        </p>
      ) : null}
      <form onSubmit={createTicket}>
        <div className="field">
          <label htmlFor="retraining-reason">Review rationale</label>
          <textarea
            id="retraining-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={4000}
            rows={3}
            placeholder="Describe the observed drift and proposed validation scope."
            required
          />
        </div>
        <label className="check-label">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
          I confirm this is a human review request, not an automatic retraining instruction.
        </label>
        <button
          type="submit"
          className="button button-primary"
          disabled={!driftDetected || !confirmed || !reason.trim() || submitting}
        >
          {submitting ? "Opening ticket…" : "Open retraining review ticket"}
        </button>
      </form>
      {!driftDetected ? <p className="field-help">A detected drift state is required before a ticket can be opened.</p> : null}
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      <h3>Open review tickets</h3>
      {loading ? <p role="status">Loading tickets…</p> : null}
      {!loading && tickets.length === 0 ? <p className="empty-state">No review tickets have been opened.</p> : null}
      <ul className="ticket-list">
        {tickets.map((ticket) => (
          <li key={ticket.id}>
            <div>
              <strong>{ticket.status}</strong>
              <span>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(ticket.created_at))}</span>
            </div>
            <p>{ticket.reason}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
