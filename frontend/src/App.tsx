import { useEffect, useRef, useState } from "react";
import { ApiError, apiClient } from "./api/client";
import { ABToggle, explanationVisible } from "./components/ABToggle";
import { ApplicationUploadForm } from "./components/ApplicationUploadForm";
import { DecisionActionBar } from "./components/DecisionActionBar";
import { DriftDashboard } from "./components/DriftDashboard";
import { ExplanationPanel } from "./components/ExplanationPanel";
import { LoginPage } from "./components/LoginPage";
import { RetrainTriggerPanel } from "./components/RetrainTriggerPanel";
import { RiskScoreCard } from "./components/RiskScoreCard";
import { useAuth } from "./context/AuthContext";
import type { DriftStatus, ExplanationAssignment, PredictionResponse } from "./types";

function ReviewConsole() {
  const { user, signOut } = useAuth();
  const [prediction, setPrediction] = useState<PredictionResponse | null>(null);
  const [assignment, setAssignment] = useState<ExplanationAssignment | null>(null);
  const [assignmentError, setAssignmentError] = useState<string | null>(null);
  const [monitoringStatus, setMonitoringStatus] = useState<DriftStatus | null>(null);
  const recordedPredictions = useRef(new Set<string>());

  const isOfficer = user?.role === "loan_officer";
  const canMonitor = user?.role === "risk_analyst" || user?.role === "admin";

  useEffect(() => {
    if (!isOfficer) {
      setAssignment(null);
      return;
    }
    let active = true;
    void apiClient
      .explanationAssignment()
      .then((nextAssignment) => {
        if (active) {
          setAssignment(nextAssignment);
          setAssignmentError(null);
        }
      })
      .catch((reason) => {
        if (active) {
          setAssignmentError(
            reason instanceof ApiError
              ? reason.detail
              : "Explanation-study assignment could not be loaded.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [isOfficer]);

  useEffect(() => {
    if (!prediction || !isOfficer || !assignment || recordedPredictions.current.has(prediction.id)) {
      return;
    }
    recordedPredictions.current.add(prediction.id);
    void apiClient.recordExplanationExposure(prediction.id).catch(() => {
      // Scoring and officer feedback remain usable if an optional experiment
      // telemetry write is temporarily unavailable.
    });
  }, [assignment, isOfficer, prediction]);

  const showExplanation = !isOfficer || explanationVisible(assignment);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Drift-aware decision support</p>
          <h1>Loan Review Console</h1>
        </div>
        <div className="user-menu">
          <span>
            {user?.username} <small>{user?.role.replaceAll("_", " ")}</small>
          </span>
          <button type="button" className="button button-secondary" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <p className="safety-banner">
        Model output is decision support only. A qualified human must make and record the final lending decision.
      </p>
      <div className="workspace-grid">
        <div className="review-column">
          <ApplicationUploadForm onPrediction={setPrediction} />
          {prediction ? (
            <div className="result-stack">
              <RiskScoreCard prediction={prediction} />
              {isOfficer ? <ABToggle assignment={assignment} /> : null}
              {assignmentError ? (
                <p className="form-error" role="alert">
                  {assignmentError}
                </p>
              ) : null}
              {showExplanation ? (
                <ExplanationPanel explanation={prediction.explanation} />
              ) : (
                <section className="panel score-only-panel" aria-live="polite">
                  <p className="eyebrow">Step 3</p>
                  <h2>Model explanation withheld</h2>
                  <p>
                    This review is assigned to the score-only study arm. Record your independent human decision below.
                  </p>
                </section>
              )}
              <DecisionActionBar key={prediction.id} prediction={prediction} />
            </div>
          ) : (
            <section className="empty-review-state" aria-live="polite">
              Enter an application to begin a human review.
            </section>
          )}
        </div>
        {canMonitor ? (
          <aside className="monitoring-column">
            <DriftDashboard onStatusChange={setMonitoringStatus} />
            <RetrainTriggerPanel status={monitoringStatus} />
          </aside>
        ) : null}
      </div>
    </main>
  );
}

export default function App() {
  const { loading, user } = useAuth();
  if (loading) {
    return <main className="loading-page" role="status">Restoring your session…</main>;
  }
  return user ? <ReviewConsole /> : <LoginPage />;
}
