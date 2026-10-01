import type {
  ApplicationDraft,
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

export function validateApplicationDraft(draft: ApplicationDraft): DataQualityResult {
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

  if (!nonEmpty(draft.issue_d)) {
    errors.issue_d = "Application month is required.";
  } else if (Number.isNaN(Date.parse(draft.issue_d))) {
    errors.issue_d = "Use a recognizable month and year, for example Jan-2018.";
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
