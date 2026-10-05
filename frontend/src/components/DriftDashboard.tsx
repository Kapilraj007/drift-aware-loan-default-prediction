import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, apiClient } from "../api/client";
import { FileParseError, parseCohortFile } from "../lib/csv";
import type { DriftStatus, MonitoringSnapshot } from "../types";
import { StatusBadge } from "./StatusBadge";

const lineColors = ["#155e75", "#7c2d12", "#6d28d9", "#9f1239", "#166534"];

function KSTrendChart({ snapshots }: { snapshots: MonitoringSnapshot[] }) {
  const series = useMemo(() => {
    const frequency = new Map<string, number>();
    for (const record of snapshots) {
      for (const item of record.snapshot.feature_results) {
        frequency.set(item.feature, (frequency.get(item.feature) ?? 0) + 1);
      }
    }
    return [...frequency.entries()]
      .sort((left, right) => right[1] - left[1])
      .slice(0, 5)
      .map(([feature]) => feature);
  }, [snapshots]);

  if (series.length === 0) {
    return <p className="empty-state">No feature KS windows have been recorded yet.</p>;
  }

  const width = 640;
  const height = 240;
  const padding = 36;
  const x = (index: number) =>
    snapshots.length === 1
      ? width / 2
      : padding + (index / (snapshots.length - 1)) * (width - padding * 2);
  const y = (value: number) => height - padding - value * (height - padding * 2);

  return (
    <figure className="ks-chart">
      <figcaption>KS statistic by recorded comparison window</figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Feature KS statistic trends across comparison windows">
        <line x1={padding} x2={padding} y1={padding} y2={height - padding} className="chart-axis" />
        <line x1={padding} x2={width - padding} y1={height - padding} y2={height - padding} className="chart-axis" />
        {[0, 0.5, 1].map((value) => (
          <g key={value}>
            <line x1={padding} x2={width - padding} y1={y(value)} y2={y(value)} className="chart-grid" />
            <text x={5} y={y(value) + 4} className="chart-label">
              {value.toFixed(1)}
            </text>
          </g>
        ))}
        {series.map((feature, featureIndex) => {
          const points = snapshots
            .map((record, index) => {
              const result = record.snapshot.feature_results.find((item) => item.feature === feature);
              return result ? `${x(index)},${y(result.statistic)}` : null;
            })
            .filter((point): point is string => point !== null)
            .join(" ");
          return points ? (
            <polyline
              key={feature}
              fill="none"
              stroke={lineColors[featureIndex]}
              strokeWidth="3"
              points={points}
            />
          ) : null;
        })}
      </svg>
      <ul className="chart-legend" aria-label="KS trend series">
        {series.map((feature, index) => (
          <li key={feature}>
            <span style={{ backgroundColor: lineColors[index] }} aria-hidden="true" />
            {feature}
          </li>
        ))}
      </ul>
    </figure>
  );
}

interface DriftDashboardProps {
  onStatusChange: (status: DriftStatus) => void;
}

export function DriftDashboard({ onStatusChange }: DriftDashboardProps) {
  const [status, setStatus] = useState<DriftStatus | null>(null);
  const [snapshots, setSnapshots] = useState<MonitoringSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [currentFile, setCurrentFile] = useState<File | null>(null);
  const [analysing, setAnalysing] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, history] = await Promise.all([apiClient.monitoringStatus(), apiClient.monitoringHistory()]);
      setStatus(nextStatus);
      setSnapshots(history.snapshots);
      onStatusChange(nextStatus);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.detail : "Monitoring data could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [onStatusChange]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function runFeatureCheck(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!referenceFile || !currentFile) {
      setError("Choose both a reference cohort and a current cohort before running a KS check.");
      return;
    }
    setAnalysing(true);
    setError(null);
    try {
      const [referenceRows, currentRows] = await Promise.all([
        parseCohortFile(referenceFile),
        parseCohortFile(currentFile),
      ]);
      if (referenceRows.length < 2 || currentRows.length < 2) {
        throw new FileParseError("Each cohort needs at least two data rows.");
      }
      const nextStatus = await apiClient.evaluateFeatureDrift(referenceRows, currentRows);
      setStatus(nextStatus);
      onStatusChange(nextStatus);
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof ApiError || reason instanceof FileParseError
          ? reason.message
          : "The feature drift check could not be completed.",
      );
    } finally {
      setAnalysing(false);
    }
  }

  return (
    <section className="panel drift-dashboard" aria-labelledby="drift-dashboard-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Monitoring</p>
          <h2 id="drift-dashboard-title">Drift dashboard</h2>
        </div>
        <button type="button" className="button button-secondary" onClick={() => void refresh()} disabled={loading}>
          Refresh
        </button>
      </div>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      {loading && !status ? <p role="status">Loading monitoring status…</p> : null}
      {status ? (
        <>
          <div className="drift-summary">
            <div>
              <span>Detector status</span>
              <StatusBadge status={status.status} />
            </div>
            <div>
              <span>ADWIN alert</span>
              <strong>{status.adwin_change_detected ? "Detected" : "Not detected"}</strong>
            </div>
            <div>
              <span>Features with KS drift</span>
              <strong>{status.feature_drift_count}</strong>
            </div>
            <div>
              <span>Observed scores</span>
              <strong>{status.score_stream_count}</strong>
            </div>
          </div>
          <KSTrendChart snapshots={snapshots} />
          {status.feature_results.length > 0 ? (
            <div className="table-scroll">
              <table>
                <caption>Latest two-sample KS comparison</caption>
                <thead>
                  <tr>
                    <th scope="col">Feature</th>
                    <th scope="col">KS statistic</th>
                    <th scope="col">p-value</th>
                    <th scope="col">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {status.feature_results.map((result) => (
                    <tr key={result.feature}>
                      <td>{result.feature}</td>
                      <td>{result.statistic.toFixed(3)}</td>
                      <td>{result.p_value.toExponential(2)}</td>
                      <td>{result.drift_detected ? "Drift detected" : "Within threshold"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : null}
      <form className="cohort-form" onSubmit={runFeatureCheck}>
        <h3>Run a feature KS check</h3>
        <p>Upload CSV or JSON arrays with matching numeric feature columns. This records a comparison window for the trend chart.</p>
        <div className="cohort-inputs">
          <label>
            Reference cohort
            <input
              type="file"
              accept=".csv,.json,application/json,text/csv"
              onChange={(event) => setReferenceFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <label>
            Current cohort
            <input
              type="file"
              accept=".csv,.json,application/json,text/csv"
              onChange={(event) => setCurrentFile(event.target.files?.[0] ?? null)}
            />
          </label>
        </div>
        <button className="button button-primary" type="submit" disabled={analysing}>
          {analysing ? "Comparing cohorts…" : "Run KS comparison"}
        </button>
      </form>
    </section>
  );
}
