import type { DataQualityResult } from "../lib/applicationData";

export function DataQualityCheck({ quality }: { quality: DataQualityResult }) {
  const errorCount = Object.keys(quality.errors).length;
  return (
    <section className="quality-check" aria-live="polite" aria-label="Data quality check">
      <div>
        <h3>Data quality</h3>
        <p className={quality.valid ? "quality-valid" : "quality-invalid"}>
          {quality.valid
            ? "Ready to save and score. Blank optional fields are sent as missing values."
            : `${errorCount} field${errorCount === 1 ? "" : "s"} need attention before scoring.`}
        </p>
      </div>
      {quality.warnings.length > 0 ? (
        <ul className="quality-warnings">
          {quality.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
