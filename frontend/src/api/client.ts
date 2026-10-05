import type {
  ApiUser,
  ApplicationResponse,
  ApplicationReviewResponse,
  ApplicationSchemaResponse,
  AuditEvent,
  DashboardSummary,
  DriftStatus,
  ExperimentSummaryResponse,
  ExplanationAssignment,
  FeedbackResponse,
  LoanApplicationFeatures,
  ManagedUser,
  ModelMetadataResponse,
  MonitoringSnapshot,
  OfficerDecision,
  PaginatedResponse,
  PredictionResponse,
  RetrainingTicket,
  RoleResponse,
  TokenResponse,
  TrainingRunsResponse,
  UserRole,
} from "../types";

export interface FieldError {
  field: string;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly code: string | null;
  readonly fieldErrors: FieldError[];
  readonly retryAfterSeconds: number | null;

  constructor(
    status: number,
    detail: string,
    options: { code?: string | null; fieldErrors?: FieldError[]; retryAfterSeconds?: number | null } = {},
  ) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = options.code ?? null;
    this.fieldErrors = options.fieldErrors ?? [];
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
  }
}

interface ErrorEnvelope {
  detail?: unknown;
  error?: unknown;
  code?: unknown;
}

interface RequestOptions extends RequestInit {
  wakeRetries?: number;
}

function asObject(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function parseError(body: unknown, fallback: string): { detail: string; code: string | null; fields: FieldError[] } {
  if (typeof body === "string" && body.trim()) {
    return { detail: body, code: null, fields: [] };
  }
  const envelope = asObject(body) as ErrorEnvelope | null;
  const codeValue = envelope?.error ?? envelope?.code;
  const code = typeof codeValue === "string" ? codeValue : null;
  const rawDetail = envelope?.detail;
  if (typeof rawDetail === "string") {
    return { detail: rawDetail, code, fields: [] };
  }
  if (Array.isArray(rawDetail)) {
    const fields = rawDetail.map((item): FieldError => {
      const row = asObject(item);
      const field = typeof row?.field === "string"
        ? row.field
        : Array.isArray(row?.loc)
          ? String(row.loc.at(-1) ?? "form")
          : "form";
      const message = typeof row?.message === "string"
        ? row.message
        : typeof row?.msg === "string"
          ? row.msg
          : "Invalid value";
      return { field, message };
    });
    return { detail: fields.map(({ message }) => message).join(" ") || fallback, code, fields };
  }
  return { detail: fallback, code, fields: [] };
}

function wait(milliseconds: number, signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("The request was cancelled.", "AbortError"));
      return;
    }
    const timer = window.setTimeout(resolve, milliseconds);
    signal?.addEventListener("abort", () => {
      window.clearTimeout(timer);
      reject(new DOMException("The request was cancelled.", "AbortError"));
    }, { once: true });
  });
}

function queryString(values: Record<string, string | number | boolean | null | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  const rendered = query.toString();
  return rendered ? `?${rendered}` : "";
}

function pageFrom<T>(response: PaginatedResponse<T> | T[], limit: number, offset: number): PaginatedResponse<T> {
  if (Array.isArray(response)) {
    return { items: response, total: response.length, limit, offset };
  }
  const record = response as PaginatedResponse<T> & { results?: T[] };
  return {
    items: record.items ?? record.results ?? [],
    total: record.total ?? record.items?.length ?? record.results?.length ?? 0,
    limit: record.limit ?? limit,
    offset: record.offset ?? offset,
  };
}

export class ApiClient {
  private token: string | null = null;
  private unauthorizedHandler: (() => void) | null = null;
  private databaseWakeHandler: ((retrying: boolean) => void) | null = null;

  constructor(private readonly baseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api/v1") {}

  setToken(token: string | null): void {
    this.token = token;
  }

  setUnauthorizedHandler(handler: (() => void) | null): void {
    this.unauthorizedHandler = handler;
  }

  setDatabaseWakeHandler(handler: ((retrying: boolean) => void) | null): void {
    this.databaseWakeHandler = handler;
  }

  private async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const { wakeRetries = 2, ...init } = options;
    const headers = new Headers(init.headers);
    if (init.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (this.token) {
      headers.set("Authorization", `Bearer ${this.token}`);
    }

    let attempt = 0;
    while (true) {
      let response: Response;
      try {
        response = await fetch(`${this.baseUrl.replace(/\/$/, "")}${path}`, { ...init, headers });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          throw error;
        }
        throw new ApiError(0, "The service could not be reached. Check that the API is running.");
      }

      const contentType = response.headers.get("content-type") ?? "";
      const body: unknown = contentType.includes("application/json")
        ? await response.json().catch(() => null)
        : await response.text().catch(() => "");
      if (response.ok) {
        this.databaseWakeHandler?.(false);
        return body as T;
      }

      const parsed = parseError(body, `Request failed (${response.status}).`);
      if (response.status === 401 && this.token) {
        this.token = null;
        this.unauthorizedHandler?.();
      }
      if (response.status === 503 && parsed.code === "database_waking" && attempt < wakeRetries) {
        this.databaseWakeHandler?.(true);
        attempt += 1;
        await wait(750 * 2 ** (attempt - 1), init.signal);
        continue;
      }
      this.databaseWakeHandler?.(false);
      const retryAfter = Number(response.headers.get("retry-after"));
      throw new ApiError(response.status, parsed.detail, {
        code: parsed.code,
        fieldErrors: parsed.fields,
        retryAfterSeconds: Number.isFinite(retryAfter) ? retryAfter : null,
      });
    }
  }

  login(username: string, password: string, signal?: AbortSignal): Promise<TokenResponse> {
    return this.request<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
      signal,
      wakeRetries: 2,
    });
  }

  currentUser(signal?: AbortSignal): Promise<ApiUser> {
    return this.request<ApiUser>("/auth/me", { signal });
  }

  changePassword(currentPassword: string, newPassword: string): Promise<void> {
    return this.request<void>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
  }

  applicationSchema(signal?: AbortSignal): Promise<ApplicationSchemaResponse> {
    return this.request<ApplicationSchemaResponse>("/reference/application-schema", { signal });
  }

  createApplication(externalReference: string | null, features: LoanApplicationFeatures): Promise<ApplicationResponse> {
    return this.request<ApplicationResponse>("/applications", {
      method: "POST",
      body: JSON.stringify({ external_reference: externalReference || null, features }),
    });
  }

  applications(params: {
    limit?: number; offset?: number; search?: string; status?: string; riskFlag?: boolean; dateFrom?: string; dateTo?: string;
  } = {}, signal?: AbortSignal): Promise<PaginatedResponse<ApplicationResponse>> {
    const limit = params.limit ?? 20;
    const offset = params.offset ?? 0;
    return this.request<PaginatedResponse<ApplicationResponse> | ApplicationResponse[]>(`/applications${queryString({
      limit,
      offset,
      search: params.search,
      status: params.status,
      risk_flag: params.riskFlag,
      date_from: params.dateFrom,
      date_to: params.dateTo,
    })}`, { signal }).then((response) => pageFrom(response, limit, offset));
  }

  application(applicationId: string, signal?: AbortSignal): Promise<ApplicationResponse> {
    return this.request<ApplicationResponse>(`/applications/${encodeURIComponent(applicationId)}`, { signal });
  }

  applicationReview(applicationId: string, signal?: AbortSignal): Promise<ApplicationReviewResponse> {
    return this.request<ApplicationReviewResponse>(`/applications/${encodeURIComponent(applicationId)}/review`, { signal });
  }

  createPrediction(applicationId: string): Promise<PredictionResponse> {
    return this.request<PredictionResponse>("/predictions", {
      method: "POST",
      body: JSON.stringify({ application_id: applicationId }),
    });
  }

  predictions(params: { limit?: number; offset?: number; applicationId?: string } = {}, signal?: AbortSignal): Promise<PaginatedResponse<PredictionResponse>> {
    const limit = params.limit ?? 50;
    const offset = params.offset ?? 0;
    return this.request<PaginatedResponse<PredictionResponse> | PredictionResponse[]>(`/predictions${queryString({
      limit, offset, application_id: params.applicationId,
    })}`, { signal }).then((response) => pageFrom(response, limit, offset));
  }

  prediction(predictionId: string, signal?: AbortSignal): Promise<PredictionResponse> {
    return this.request<PredictionResponse>(`/predictions/${encodeURIComponent(predictionId)}`, { signal });
  }

  submitFeedback(predictionId: string, decision: OfficerDecision, agreedWithModel: boolean | null, note: string | null): Promise<FeedbackResponse> {
    return this.request<FeedbackResponse>("/feedback", {
      method: "POST",
      body: JSON.stringify({ prediction_id: predictionId, decision, agreed_with_model: agreedWithModel, note: note || null }),
    });
  }

  feedback(params: { limit?: number; offset?: number; predictionId?: string } = {}, signal?: AbortSignal): Promise<PaginatedResponse<FeedbackResponse>> {
    const limit = params.limit ?? 100;
    const offset = params.offset ?? 0;
    return this.request<PaginatedResponse<FeedbackResponse> | FeedbackResponse[]>(`/feedback${queryString({
      limit, offset, prediction_id: params.predictionId,
    })}`, { signal }).then((response) => pageFrom(response, limit, offset));
  }

  explanationAssignment(signal?: AbortSignal): Promise<ExplanationAssignment> {
    return this.request<ExplanationAssignment>("/experiments/explanation-assignment", { signal });
  }

  experimentSummary(signal?: AbortSignal): Promise<ExperimentSummaryResponse> {
    return this.request<ExperimentSummaryResponse>("/experiments/summary", { signal });
  }

  recordExplanationExposure(predictionId: string): Promise<void> {
    return this.request<void>("/experiments/explanation-exposures", {
      method: "POST",
      body: JSON.stringify({ prediction_id: predictionId }),
    });
  }

  dashboardSummary(signal?: AbortSignal): Promise<DashboardSummary> {
    return this.request<DashboardSummary>("/dashboard/summary", { signal });
  }

  monitoringStatus(signal?: AbortSignal): Promise<DriftStatus> {
    return this.request<DriftStatus>("/monitoring/status", { signal });
  }

  monitoringHistory(limit = 60, signal?: AbortSignal): Promise<{ snapshots: MonitoringSnapshot[] }> {
    return this.request<{ snapshots: MonitoringSnapshot[] }>(`/monitoring/history${queryString({ limit })}`, { signal });
  }

  evaluateFeatureDrift(referenceRows: Record<string, unknown>[], currentRows: Record<string, unknown>[], alpha = 0.01): Promise<DriftStatus> {
    return this.request<DriftStatus>("/monitoring/feature-drift", {
      method: "POST",
      body: JSON.stringify({ reference_rows: referenceRows, current_rows: currentRows, alpha }),
    });
  }

  retrainingTickets(signal?: AbortSignal): Promise<RetrainingTicket[]> {
    return this.request<RetrainingTicket[] | PaginatedResponse<RetrainingTicket>>("/retraining-tickets", { signal })
      .then((response) => Array.isArray(response) ? response : response.items);
  }

  createRetrainingTicket(reason: string): Promise<RetrainingTicket> {
    return this.request<RetrainingTicket>("/retraining-tickets", {
      method: "POST",
      body: JSON.stringify({ reason, human_review_confirmed: true }),
    });
  }

  reviewRetrainingTicket(ticketId: string, decision: "approve" | "reject", note: string | null): Promise<RetrainingTicket> {
    return this.request<RetrainingTicket>(`/retraining-tickets/${encodeURIComponent(ticketId)}/review`, {
      method: "POST",
      body: JSON.stringify({ decision, note: note || null }),
    });
  }

  model(signal?: AbortSignal): Promise<ModelMetadataResponse> {
    return this.request<ModelMetadataResponse>("/model", { signal });
  }

  trainingRuns(signal?: AbortSignal): Promise<TrainingRunsResponse> {
    return this.request<TrainingRunsResponse>("/training-runs", { signal });
  }

  users(params: { limit?: number; offset?: number; search?: string; active?: boolean } = {}, signal?: AbortSignal): Promise<PaginatedResponse<ManagedUser>> {
    const limit = params.limit ?? 20;
    const offset = params.offset ?? 0;
    return this.request<PaginatedResponse<ManagedUser> | ManagedUser[]>(`/users${queryString({
      limit, offset, search: params.search, active: params.active,
    })}`, { signal }).then((response) => pageFrom(response, limit, offset));
  }

  createUser(payload: { username: string; full_name?: string; email?: string; role: UserRole; password: string }): Promise<ManagedUser> {
    return this.request<ManagedUser>("/users", { method: "POST", body: JSON.stringify(payload) });
  }

  updateUser(userId: string, payload: Partial<{ full_name: string; email: string; role: UserRole; is_active: boolean }>): Promise<ManagedUser> {
    return this.request<ManagedUser>(`/users/${encodeURIComponent(userId)}`, { method: "PATCH", body: JSON.stringify(payload) });
  }

  resetUserPassword(userId: string): Promise<{ temporary_password: string }> {
    return this.request<{ temporary_password: string }>(`/users/${encodeURIComponent(userId)}/reset-password`, { method: "POST" });
  }

  roles(signal?: AbortSignal): Promise<RoleResponse[]> {
    return this.request<RoleResponse[]>("/roles", { signal });
  }

  auditEvents(params: { limit?: number; offset?: number; action?: string; actor?: string } = {}, signal?: AbortSignal): Promise<PaginatedResponse<AuditEvent>> {
    const limit = params.limit ?? 25;
    const offset = params.offset ?? 0;
    return this.request<PaginatedResponse<AuditEvent> | AuditEvent[]>(`/audit-events${queryString({
      limit, offset, action: params.action, actor: params.actor,
    })}`, { signal }).then((response) => pageFrom(response, limit, offset));
  }
}

export const apiClient = new ApiClient();
