export type UserRole = "loan_officer" | "risk_analyst" | "admin";

export interface ApiUser {
  id: string;
  username: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in_seconds: number;
}

export interface LoanApplicationFeatures {
  annual_inc: number | null;
  dti: number | null;
  revol_util: number | string | null;
  revol_bal: number | null;
  open_acc: number | null;
  total_acc: number | null;
  delinq_2yrs: number | null;
  inq_last_6mths: number | null;
  loan_amnt: number | null;
  term: number | string | null;
  int_rate: number | string | null;
  installment: number | null;
  grade: string | null;
  sub_grade: string | null;
  purpose: string | null;
  emp_length: number | string | null;
  home_ownership: string | null;
  earliest_cr_line: string | null;
  issue_d: string;
}

export type ApplicationFeatureName = keyof LoanApplicationFeatures;
export type ApplicationDraft = Record<ApplicationFeatureName, string>;

export interface ApplicationResponse {
  id: string;
  external_reference: string | null;
  features: LoanApplicationFeatures;
  created_by_id: string;
  created_at: string;
}

export interface FeatureContribution {
  feature: string;
  display_name: string;
  contribution: number;
  direction: "risk_increasing" | "risk_reducing" | string;
  feature_value: number | string | null;
}

export interface ExplanationResponse {
  available: boolean;
  narrative: string;
  top_features: FeatureContribution[];
}

export type DetectorStatus = "stable" | "watch" | "drift_detected" | "not_observed" | string;

export interface FeatureDriftResult {
  feature: string;
  statistic: number;
  p_value: number;
  drift_detected: boolean;
  reference_count: number;
  current_count: number;
}

export interface DriftStatus {
  status: DetectorStatus;
  score_stream_count: number;
  latest_score: number | null;
  adwin_change_detected: boolean;
  feature_drift_count: number;
  updated_at: string | null;
  feature_results: FeatureDriftResult[];
}

export interface PredictionResponse {
  id: string;
  application_id: string | null;
  model_version: string;
  score: number;
  threshold: number;
  risk_flag: boolean;
  explanation: ExplanationResponse;
  study_variant?: ExplanationVariant | null;
  detector_state: DriftStatus;
  created_at: string;
}

export type OfficerDecision = "approve" | "decline" | "escalate";

export interface FeedbackResponse {
  id: string;
  prediction_id: string;
  officer_id: string;
  decision: OfficerDecision;
  agreed_with_model: boolean | null;
  note: string | null;
  detector_state: DriftStatus;
  created_at: string;
}

export type ExplanationVariant = "explanation_shown" | "score_only";

export interface ExplanationAssignment {
  id: string;
  variant: ExplanationVariant;
  created_at: string;
}

export interface MonitoringSnapshot {
  id: string;
  source: "prediction" | "feature_drift" | "feedback" | string;
  snapshot: DriftStatus;
  created_at: string;
}

export interface RetrainingTicket {
  id: string;
  monitoring_snapshot_id: string;
  requested_by_id: string;
  reason: string;
  human_review_confirmed: boolean;
  status: "open" | "approved" | "rejected" | string;
  reviewed_by_id: string | null;
  review_note: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface ApplicationFieldDefinition {
  name: ApplicationFeatureName;
  label: string;
  kind: "number" | "text" | "select";
  group: "Financial profile" | "Loan details" | "Credit history";
  options?: readonly string[];
  required?: boolean;
  placeholder?: string;
  help?: string;
}

export const applicationFields: readonly ApplicationFieldDefinition[] = [
  {
    name: "annual_inc",
    label: "Annual income",
    kind: "number",
    group: "Financial profile",
    placeholder: "75000",
    help: "Enter annual income before tax, if available.",
  },
  {
    name: "dti",
    label: "Debt-to-income ratio",
    kind: "number",
    group: "Financial profile",
    placeholder: "16.5",
    help: "Percentage without the percent sign.",
  },
  {
    name: "revol_util",
    label: "Revolving utilization",
    kind: "text",
    group: "Financial profile",
    placeholder: "38%",
  },
  { name: "revol_bal", label: "Revolving balance", kind: "number", group: "Financial profile" },
  { name: "open_acc", label: "Open accounts", kind: "number", group: "Credit history" },
  { name: "total_acc", label: "Total accounts", kind: "number", group: "Credit history" },
  {
    name: "delinq_2yrs",
    label: "Delinquencies in last 2 years",
    kind: "number",
    group: "Credit history",
  },
  {
    name: "inq_last_6mths",
    label: "Inquiries in last 6 months",
    kind: "number",
    group: "Credit history",
  },
  { name: "loan_amnt", label: "Loan amount", kind: "number", group: "Loan details" },
  {
    name: "term",
    label: "Term",
    kind: "select",
    group: "Loan details",
    options: ["36 months", "60 months"],
  },
  {
    name: "int_rate",
    label: "Interest rate",
    kind: "text",
    group: "Loan details",
    placeholder: "11.2%",
  },
  { name: "installment", label: "Monthly installment", kind: "number", group: "Loan details" },
  {
    name: "grade",
    label: "Grade",
    kind: "select",
    group: "Loan details",
    options: ["A", "B", "C", "D", "E", "F", "G"],
  },
  {
    name: "sub_grade",
    label: "Sub-grade",
    kind: "text",
    group: "Loan details",
    placeholder: "B3",
  },
  { name: "purpose", label: "Purpose", kind: "text", group: "Loan details" },
  {
    name: "emp_length",
    label: "Employment length",
    kind: "text",
    group: "Financial profile",
    placeholder: "5 years",
  },
  {
    name: "home_ownership",
    label: "Home ownership",
    kind: "select",
    group: "Financial profile",
    options: ["RENT", "MORTGAGE", "OWN", "OTHER", "NONE", "ANY"],
  },
  {
    name: "earliest_cr_line",
    label: "Earliest credit line",
    kind: "text",
    group: "Credit history",
    placeholder: "Jan-2004",
  },
  {
    name: "issue_d",
    label: "Application month",
    kind: "text",
    group: "Loan details",
    required: true,
    placeholder: "Jan-2018",
    help: "Required. Use a month and year, for example Jan-2018.",
  },
];

export function emptyApplicationDraft(): ApplicationDraft {
  return Object.fromEntries(applicationFields.map(({ name }) => [name, ""])) as ApplicationDraft;
}
