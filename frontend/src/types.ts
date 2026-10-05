import type { components } from "./api/openapi.generated";

type ApiSchemas = components["schemas"];

export type UserRole = ApiSchemas["UserRole"];

export type Permission =
  | "application:create"
  | "application:read_own"
  | "application:read_all"
  | "prediction:create"
  | "prediction:read_own"
  | "prediction:read_all"
  | "feedback:create"
  | "feedback:read_own"
  | "feedback:read_all"
  | "experiment:participate"
  | "experiment:read_results"
  | "monitoring:read"
  | "monitoring:run_check"
  | "retraining:create"
  | "retraining:read"
  | "retraining:review"
  | "model:read"
  | "dashboard:read"
  | "user:manage"
  | "role:read"
  | "audit:read";

export const ROLE_PERMISSION_FALLBACK: Record<UserRole, readonly Permission[]> = {
  loan_officer: [
    "application:create",
    "application:read_own",
    "prediction:create",
    "prediction:read_own",
    "feedback:create",
    "feedback:read_own",
    "experiment:participate",
    "dashboard:read",
  ],
  risk_analyst: [
    "application:create",
    "application:read_all",
    "prediction:create",
    "prediction:read_all",
    "feedback:create",
    "feedback:read_all",
    "monitoring:read",
    "monitoring:run_check",
    "retraining:create",
    "retraining:read",
    "model:read",
    "experiment:read_results",
    "dashboard:read",
  ],
  admin: [
    "application:create",
    "application:read_all",
    "prediction:create",
    "prediction:read_all",
    "feedback:create",
    "feedback:read_all",
    "monitoring:read",
    "monitoring:run_check",
    "retraining:create",
    "retraining:read",
    "retraining:review",
    "model:read",
    "experiment:read_results",
    "dashboard:read",
    "user:manage",
    "role:read",
    "audit:read",
  ],
};

export interface ApiUser {
  id: string;
  username: string;
  role: UserRole;
  permissions?: Permission[];
  email?: string | null;
  full_name?: string | null;
  must_change_password?: boolean;
  is_active: boolean;
  last_login_at?: string | null;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in_seconds: number;
}

export type LoanApplicationFeatures = ApiSchemas["LoanApplicationFeatures"];

export type ApplicationFeatureName = keyof LoanApplicationFeatures;
export type ApplicationDraft = Record<ApplicationFeatureName, string>;

export interface ApplicationResponse {
  id: string;
  external_reference: string | null;
  features: LoanApplicationFeatures;
  created_by_id: string;
  status?: "scored" | "decided" | "escalated" | string;
  latest_prediction_id?: string | null;
  latest_score?: number | null;
  score?: number | null;
  risk_flag?: boolean | null;
  current_decision?: OfficerDecision | null;
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

export type OfficerDecision = ApiSchemas["OfficerDecision"];

export interface FeedbackResponse {
  id: string;
  prediction_id: string;
  officer_id: string;
  decision: OfficerDecision;
  agreed_with_model: boolean | null;
  note: string | null;
  is_current?: boolean;
  amendment_number?: number;
  version?: number;
  amends_feedback_id?: string | null;
  detector_state: DriftStatus;
  created_at: string;
}

export type ExplanationVariant = ApiSchemas["ExplanationVariant"];

export interface ExplanationAssignment {
  id: string;
  variant: ExplanationVariant;
  created_at: string;
}

export interface MonitoringSnapshot {
  id: string;
  source: "score_observation" | "feature_drift";
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

export type FieldKind = "number" | "text" | "select" | "month";

export interface ApplicationFieldDefinition {
  name: ApplicationFeatureName;
  label: string;
  kind: FieldKind;
  type?: string;
  group: "Applicant & finances" | "Financial profile" | "Loan details" | "Credit history" | string;
  options?: readonly (string | number)[];
  allowed_values?: readonly (string | number)[];
  required?: boolean;
  nullable?: boolean;
  placeholder?: string;
  help?: string;
  help_text?: string;
  description?: string;
  format?: string | null;
  minimum?: number | null;
  maximum?: number | null;
}

export interface ApplicationSchemaResponse {
  fields: ApplicationFieldDefinition[];
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ApplicationReviewResponse {
  application: ApplicationResponse;
  latest_prediction: PredictionResponse | null;
  feedback_history: FeedbackResponse[];
  current_feedback?: FeedbackResponse | null;
}

export interface DashboardSummary {
  applications: number;
  scored: number;
  decided: number;
  pending: number;
  awaiting_decision?: number;
  risk_flag_rate: number | null;
  agreement_rate?: number | null;
  override_rate: number | null;
  open_tickets: number;
  drift_status: DriftStatus | null;
  latest_drift_status?: DetectorStatus;
  decision_mix?: Partial<Record<OfficerDecision, number>>;
  score_distribution?: Array<{ bucket?: string; minimum?: number; maximum?: number; count: number }>;
  recent_applications?: ApplicationResponse[];
}

export interface ModelMetadataResponse {
  model_version: string;
  feature_view: string;
  prediction_threshold: number;
  feature_count: number;
  feature_schema_sha256: string;
  synthetic_demo?: boolean;
  metadata: Record<string, unknown>;
}

export interface TrainingRunsResponse {
  runs: Array<Record<string, unknown>>;
  synthetic_demo?: boolean;
}

export interface ExperimentArmSummary {
  variant: ExplanationVariant;
  exposures: number;
  decisions: number;
  agreement_rate: number | null;
  override_rate: number | null;
}

export interface ExperimentSummaryResponse {
  arms: ExperimentArmSummary[];
  note?: string;
}

export interface RoleResponse {
  id: string;
  name: string;
  description: string;
  is_system: boolean;
  permissions: Permission[];
}

export interface ManagedUser extends ApiUser {
  role_id?: string;
}

export interface AuditEvent {
  id: string;
  actor_user_id: string | null;
  actor_username?: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  metadata?: Record<string, unknown>;
  ip?: string | null;
  created_at: string;
}

export const applicationFields: readonly ApplicationFieldDefinition[] = [
  { name: "annual_inc", label: "Annual income", kind: "number", group: "Applicant & finances", placeholder: "75000", help: "Annual income before tax, in USD." },
  { name: "dti", label: "Debt-to-income ratio", kind: "number", group: "Applicant & finances", placeholder: "16.5", help: "Percentage without the percent sign." },
  { name: "revol_util", label: "Revolving utilization", kind: "text", group: "Applicant & finances", placeholder: "38%" },
  { name: "revol_bal", label: "Revolving balance", kind: "number", group: "Applicant & finances" },
  { name: "emp_length", label: "Employment length", kind: "select", group: "Applicant & finances", options: ["< 1 year", "1 year", "2 years", "3 years", "4 years", "5 years", "6 years", "7 years", "8 years", "9 years", "10+ years", "n/a"] },
  { name: "home_ownership", label: "Home ownership", kind: "select", group: "Applicant & finances", options: ["RENT", "MORTGAGE", "OWN", "OTHER", "NONE", "ANY"] },
  { name: "loan_amnt", label: "Loan amount", kind: "number", group: "Loan details" },
  { name: "term", label: "Term", kind: "select", group: "Loan details", options: ["36 months", "60 months"] },
  { name: "int_rate", label: "Interest rate", kind: "text", group: "Loan details", placeholder: "11.2%" },
  { name: "installment", label: "Monthly installment", kind: "number", group: "Loan details" },
  { name: "grade", label: "Grade", kind: "select", group: "Loan details", options: ["A", "B", "C", "D", "E", "F", "G"] },
  { name: "sub_grade", label: "Sub-grade", kind: "text", group: "Loan details", placeholder: "B3" },
  { name: "purpose", label: "Purpose", kind: "select", group: "Loan details", options: ["debt_consolidation", "credit_card", "home_improvement", "major_purchase", "small_business", "medical", "car", "moving", "vacation", "house", "renewable_energy", "wedding", "other"] },
  { name: "issue_d", label: "Application month", kind: "month", group: "Loan details", required: true, placeholder: "Jan-2018", help: "Month when this application was created." },
  { name: "open_acc", label: "Open accounts", kind: "number", group: "Credit history" },
  { name: "total_acc", label: "Total accounts", kind: "number", group: "Credit history" },
  { name: "delinq_2yrs", label: "Delinquencies in last 2 years", kind: "number", group: "Credit history" },
  { name: "inq_last_6mths", label: "Inquiries in last 6 months", kind: "number", group: "Credit history" },
  { name: "earliest_cr_line", label: "Earliest credit line", kind: "month", group: "Credit history", placeholder: "Jan-2004" },
];

export function emptyApplicationDraft(): ApplicationDraft {
  return Object.fromEntries(applicationFields.map(({ name }) => [name, ""])) as ApplicationDraft;
}
