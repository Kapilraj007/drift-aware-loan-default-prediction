import type {
  ApplicationDraft,
  ApplicationFieldDefinition,
  ApplicationFeatureName,
  LoanApplicationFeatures,
} from "../types";
import { emptyApplicationDraft } from "../types";

const numericFields = new Set<ApplicationFeatureName>([
  "annual_inc",
  "dti",
  "revol_bal",
  "open_acc",
  "total_acc",
  "delinq_2yrs",
  "inq_last_6mths",
  "loan_amnt",
  "installment",
]);

const nonNegativeFields = new Set<ApplicationFeatureName>([
  "annual_inc",
  "dti",
  "revol_bal",
  "open_acc",
  "total_acc",
  "delinq_2yrs",
  "inq_last_6mths",
  "loan_amnt",
  "installment",
]);

export interface DataQualityResult {
  errors: Partial<Record<ApplicationFeatureName, string>>;
  warnings: string[];
  valid: boolean;
}

function nonEmpty(value: string): string {
  return value.trim();
}

const validMonth = /^(?:[A-Z][a-z]{2}-(?:\d{2}|\d{4})|\d{4}-(?:0[1-9]|1[0-2])(?:-\d{2})?)$/;

export function validateApplicationDraft(
  draft: ApplicationDraft,
  fields: readonly ApplicationFieldDefinition[] = [],
): DataQualityResult {
  const errors: Partial<Record<ApplicationFeatureName, string>> = {};
  const warnings: string[] = [];

  for (const field of numericFields) {
    const value = nonEmpty(draft[field]);
    if (!value) {
      continue;
    }
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
      errors[field] = "Enter a valid number or leave this field blank.";
    } else if (nonNegativeFields.has(field) && parsed < 0) {
      errors[field] = "Enter zero or a positive number.";
    }
  }

  const definitions = new Map(fields.map((field) => [field.name, field]));
  for (const [name, definition] of definitions) {
    const value = nonEmpty(draft[name]);
    if (definition.required && !value) {
      errors[name] = `${definition.label} is required.`;
    }
    if (value && definition.allowed_values?.length) {
      const allowed = definition.allowed_values.map(String);
      const termAliases = name === "term" && allowed.includes(value.replace(/\s+months?$/i, ""));
      if (!allowed.includes(value) && !termAliases) {
        errors[name] = `Choose one of the allowed ${definition.label.toLowerCase()} values.`;
      }
    }
  }

  if (!nonEmpty(draft.issue_d)) {
    errors.issue_d = "Application month is required.";
  } else if (!validMonth.test(nonEmpty(draft.issue_d))) {
    errors.issue_d = "Use Mon-YYYY, Mon-YY, or an ISO month, for example Jan-2018.";
  }

  if (nonEmpty(draft.earliest_cr_line) && !validMonth.test(nonEmpty(draft.earliest_cr_line))) {
    errors.earliest_cr_line = "Use Mon-YYYY, Mon-YY, or an ISO month, for example Jan-2004.";
  }
  if (nonEmpty(draft.term) && !/^(?:36|60)(?:\.0)?(?: months?)?$/i.test(nonEmpty(draft.term))) {
    errors.term = "Term must be 36 or 60 months.";
  }
  if (nonEmpty(draft.emp_length) && !/^(?:n\/?a|<\s*1 year|less than 1 year|\d+(?:\.\d+)?\+?\s*(?:years?)?)$/i.test(nonEmpty(draft.emp_length))) {
    errors.emp_length = "Use a number of years, < 1 year, 10+ years, or n/a.";
  }
  if (nonEmpty(draft.sub_grade) && !/^[A-G][1-5]$/.test(nonEmpty(draft.sub_grade))) {
    errors.sub_grade = "Sub-grade must be A1 through G5.";
  }

  if (nonEmpty(draft.dti) && Number(draft.dti) > 100) {
    warnings.push("Debt-to-income ratio is above 100%; verify that the value is intentional.");
  }
  if (nonEmpty(draft.int_rate) && !/^-?\d+(\.\d+)?%?$/.test(nonEmpty(draft.int_rate))) {
    warnings.push("Interest rate is normally entered as a number or a percentage, for example 11.2%.");
  }
  if (nonEmpty(draft.revol_util) && !/^-?\d+(\.\d+)?%?$/.test(nonEmpty(draft.revol_util))) {
    warnings.push("Revolving utilization is normally entered as a number or a percentage, for example 38%.");
  }

  return { errors, warnings, valid: Object.keys(errors).length === 0 };
}

export function toApplicationFeatures(draft: ApplicationDraft): LoanApplicationFeatures {
  const output = {} as Record<ApplicationFeatureName, string | number | null>;
  for (const [key, originalValue] of Object.entries(draft) as [ApplicationFeatureName, string][]) {
    const value = nonEmpty(originalValue);
    if (key === "issue_d") {
      output.issue_d = value;
    } else if (numericFields.has(key)) {
      output[key] = value ? Number(value) : null;
    } else {
      output[key] = value || null;
    }
  }
  return output as LoanApplicationFeatures;
}

export function draftFromRecord(record: Record<string, unknown>): ApplicationDraft {
  const draft = emptyApplicationDraft();
  // Object keys are enumerated from a freshly allocated record below so every
  // backend-required field is preserved, even when a CSV omits it.
  const fields = [
    "annual_inc", "dti", "revol_util", "revol_bal", "open_acc", "total_acc", "delinq_2yrs",
    "inq_last_6mths", "loan_amnt", "term", "int_rate", "installment", "grade", "sub_grade",
    "purpose", "emp_length", "home_ownership", "earliest_cr_line", "issue_d",
  ] as const satisfies readonly ApplicationFeatureName[];
  for (const field of fields) {
    const value = record[field];
    draft[field] = value === undefined || value === null ? "" : String(value).trim();
  }
  return draft;
}
