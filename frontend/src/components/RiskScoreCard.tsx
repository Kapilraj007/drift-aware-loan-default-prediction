import type { PredictionResponse } from "../types";
import { StatusBadge } from "./StatusBadge";

export function RiskScoreCard({ prediction }: { prediction: PredictionResponse }) {
  const scorePercent = Math.round(prediction.score * 100);
  const thresholdPercent = Math.round(prediction.threshold * 100);
  return (
    <section className="panel score-card" aria-labelledby="risk-score-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Step 2</p>
          <h2 id="risk-score-title">Risk score</h2>
        </div>
        <StatusBadge status={prediction.detector_state.status} />
      </div>
      <div className="score-layout">
        <div>
          <p className="score-value" aria-label={`Default-risk score ${scorePercent} percent`}>
            {scorePercent}%
          </p>
          <p className={prediction.risk_flag ? "risk-flag risk-high" : "risk-flag risk-low"}>
            {prediction.risk_flag ? "Above review threshold" : "Below review threshold"}
          </p>
        </div>
        <dl className="score-details">
          <div>
            <dt>Review threshold</dt>
            <dd>{thresholdPercent}%</dd>
          </div>
          <div>
            <dt>Model version</dt>
            <dd>{prediction.model_version}</dd>
          </div>
          <div>
            <dt>Scored</dt>
            <dd>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(prediction.created_at))}</dd>
          </div>
        </dl>
      </div>
      <p className="decision-support-note">
        This score supports review; it does not approve, decline, or replace an officer decision.
      </p>
    </section>
  );
}
