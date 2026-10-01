import type { ExplanationResponse } from "../types";

function signedPercent(value: number): string {
  const percentage = Math.abs(value * 100).toFixed(1);
  return `${value >= 0 ? "+" : "−"}${percentage}`;
}

export function ExplanationPanel({ explanation }: { explanation: ExplanationResponse }) {
  if (!explanation.available) {
    return (
      <section className="panel explanation-panel" aria-labelledby="explanation-title">
        <p className="eyebrow">Step 3</p>
        <h2 id="explanation-title">Model explanation</h2>
        <p role="status">{explanation.narrative}</p>
      </section>
    );
  }

  const topFeatures = explanation.top_features.slice(0, 5);
  const maximum = Math.max(...topFeatures.map((item) => Math.abs(item.contribution)), 0.0001);
  return (
    <section className="panel explanation-panel" aria-labelledby="explanation-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Step 3</p>
          <h2 id="explanation-title">Model explanation</h2>
        </div>
        <span className="explanation-key" aria-label="Bar color key">
          <span className="key-increase">Increase risk</span>
          <span className="key-reduce">Reduce risk</span>
        </span>
      </div>
      <p className="narrative">{explanation.narrative}</p>
      {topFeatures.length > 0 ? (
        <div className="shap-chart" role="list" aria-label="Top feature contributions to the model score">
          {topFeatures.map((item) => {
            const increasing = item.contribution >= 0;
            const width = `${Math.max(4, (Math.abs(item.contribution) / maximum) * 100)}%`;
            return (
              <div className="shap-row" key={item.feature} role="listitem">
                <div className="shap-feature">
                  <span>{item.display_name}</span>
                  {item.feature_value !== null ? <small>Value: {String(item.feature_value)}</small> : null}
                </div>
                <div className="shap-track" aria-hidden="true">
                  <div
                    className={`shap-bar ${increasing ? "shap-increase" : "shap-reduce"}`}
                    style={{ width }}
                  />
                </div>
                <span className={`shap-value ${increasing ? "shap-increase-text" : "shap-reduce-text"}`}>
                  {signedPercent(item.contribution)}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <p>No material feature contributions were returned for this score.</p>
      )}
      <p className="assistive-note">
        Contributions describe how the model score moved for this application. They are not reasons to make an automated lending decision.
      </p>
    </section>
  );
}
