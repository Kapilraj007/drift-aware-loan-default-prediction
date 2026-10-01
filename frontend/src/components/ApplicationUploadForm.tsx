import { useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, apiClient } from "../api/client";
import { emptyApplicationDraft, applicationFields, type ApplicationDraft, type PredictionResponse } from "../types";
import { draftFromRecord, toApplicationFeatures, validateApplicationDraft } from "../lib/applicationData";
import { FileParseError, parseApplicationFile } from "../lib/csv";
import { DataQualityCheck } from "./DataQualityCheck";

interface ApplicationUploadFormProps {
  onPrediction: (prediction: PredictionResponse) => void;
}

export function ApplicationUploadForm({ onPrediction }: ApplicationUploadFormProps) {
  const [draft, setDraft] = useState<ApplicationDraft>(emptyApplicationDraft);
  const [externalReference, setExternalReference] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);
  const quality = useMemo(() => validateApplicationDraft(draft), [draft]);

  function updateField(name: keyof ApplicationDraft, value: string) {
    setDraft((current) => ({ ...current, [name]: value }));
  }

  async function loadFile(file: File) {
    setFormError(null);
    try {
      const data = await parseApplicationFile(file);
      setDraft(draftFromRecord(data));
      if (typeof data.external_reference === "string") {
        setExternalReference(data.external_reference);
      }
    } catch (reason) {
      setFormError(reason instanceof FileParseError ? reason.message : "The application file could not be read.");
    } finally {
      if (uploadRef.current) {
        uploadRef.current.value = "";
      }
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    if (!quality.valid) {
      setFormError("Correct the highlighted fields before requesting a risk score.");
      return;
    }
    setSubmitting(true);
    try {
      const application = await apiClient.createApplication(externalReference.trim() || null, toApplicationFeatures(draft));
      const prediction = await apiClient.createPrediction(application.id);
      onPrediction(prediction);
    } catch (reason) {
      setFormError(
        reason instanceof ApiError
          ? reason.detail
          : "The application could not be scored. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const groups = ["Financial profile", "Loan details", "Credit history"] as const;
  return (
    <section className="panel application-panel" aria-labelledby="application-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Step 1</p>
          <h2 id="application-title">Application entry</h2>
          <p>Enter one pre-origination application or load its first row from a CSV or JSON file.</p>
        </div>
        <div className="file-upload">
          <label className="button button-secondary" htmlFor="application-file">
            Load CSV or JSON
          </label>
          <input
            ref={uploadRef}
            id="application-file"
            type="file"
            accept=".csv,application/json,.json,text/csv"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                void loadFile(file);
              }
            }}
          />
        </div>
      </div>
      <form onSubmit={handleSubmit} noValidate>
        <div className="field external-reference-field">
          <label htmlFor="external-reference">Application reference</label>
          <input
            id="external-reference"
            value={externalReference}
            onChange={(event) => setExternalReference(event.target.value)}
            maxLength={128}
            placeholder="Optional case reference"
          />
        </div>
        {groups.map((group) => (
          <fieldset key={group} className="field-group">
            <legend>{group}</legend>
            <div className="form-grid">
              {applicationFields
                .filter((field) => field.group === group)
                .map((field) => {
                  const error = quality.errors[field.name];
                  const descriptionId = `${field.name}-help`;
                  return (
                    <div className="field" key={field.name}>
                      <label htmlFor={field.name}>
                        {field.label}
                        {field.required ? <span aria-hidden="true"> *</span> : null}
                      </label>
                      {field.kind === "select" ? (
                        <select
                          id={field.name}
                          value={draft[field.name]}
                          onChange={(event) => updateField(field.name, event.target.value)}
                          aria-invalid={Boolean(error)}
                          aria-describedby={field.help || error ? descriptionId : undefined}
                        >
                          <option value="">Not provided</option>
                          {field.options?.map((option) => (
                            <option key={option} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          id={field.name}
                          type={field.kind === "number" ? "number" : "text"}
                          inputMode={field.kind === "number" ? "decimal" : undefined}
                          value={draft[field.name]}
                          onChange={(event) => updateField(field.name, event.target.value)}
                          aria-invalid={Boolean(error)}
                          aria-describedby={field.help || error ? descriptionId : undefined}
                          placeholder={field.placeholder}
                          step="any"
                        />
                      )}
                      {error ? (
                        <p id={descriptionId} className="field-error">
                          {error}
                        </p>
                      ) : field.help ? (
                        <p id={descriptionId} className="field-help">
                          {field.help}
                        </p>
                      ) : null}
                    </div>
                  );
                })}
            </div>
          </fieldset>
        ))}
        <DataQualityCheck quality={quality} />
        {formError ? (
          <p className="form-error" role="alert">
            {formError}
          </p>
        ) : null}
        <button type="submit" className="button button-primary" disabled={submitting}>
          {submitting ? "Saving application and scoring…" : "Save and score application"}
        </button>
      </form>
    </section>
  );
}
