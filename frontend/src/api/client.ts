import type {
  ApiUser,
  ApplicationResponse,
  DriftStatus,
  ExplanationAssignment,
  FeedbackResponse,
  LoanApplicationFeatures,
  MonitoringSnapshot,
  OfficerDecision,
  PredictionResponse,
  RetrainingTicket,
  TokenResponse,
} from "../types";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function detailFromBody(body: unknown, fallback: string): string {
  if (typeof body === "string") {
    return body;
  }
  if (body && typeof body === "object" && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail
        .map((item) => (typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item)))
        .join(" ");
    }
  }
  return fallback;
}

export class ApiClient {
  private token: string | null = null;

  constructor(private readonly baseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api/v1") {}

  setToken(token: string | null): void {
    this.token = token;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (this.token) {
      headers.set("Authorization", `Bearer ${this.token}`);
    }

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl.replace(/\/$/, "")}${path}`, { ...init, headers });
    } catch {
      throw new ApiError(0, "The service could not be reached. Check that the API is running.");
    }

    const contentType = response.headers.get("content-type") ?? "";
    const body: unknown = contentType.includes("application/json")
      ? await response.json().catch(() => null)
      : await response.text().catch(() => "");
    if (!response.ok) {
      throw new ApiError(response.status, detailFromBody(body, `Request failed (${response.status}).`));
    }
    return body as T;
  }

  login(username: string, password: string): Promise<TokenResponse> {
    return this.request<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
  }

  currentUser(): Promise<ApiUser> {
    return this.request<ApiUser>("/auth/me");
  }

  createApplication(
    externalReference: string | null,
    features: LoanApplicationFeatures,
  ): Promise<ApplicationResponse> {
    return this.request<ApplicationResponse>("/applications", {
      method: "POST",
      body: JSON.stringify({ external_reference: externalReference || null, features }),
    });
  }

  createPrediction(applicationId: string): Promise<PredictionResponse> {
    return this.request<PredictionResponse>("/predictions", {
      method: "POST",
      body: JSON.stringify({ application_id: applicationId }),
    });
  }

  submitFeedback(
    predictionId: string,
    decision: OfficerDecision,
    agreedWithModel: boolean | null,
    note: string | null,
  ): Promise<FeedbackResponse> {
    return this.request<FeedbackResponse>("/feedback", {
      method: "POST",
      body: JSON.stringify({
        prediction_id: predictionId,
        decision,
        agreed_with_model: agreedWithModel,
        note: note || null,
      }),
    });
  }

  explanationAssignment(): Promise<ExplanationAssignment> {
    return this.request<ExplanationAssignment>("/experiments/explanation-assignment");
  }

  recordExplanationExposure(predictionId: string): Promise<void> {
    return this.request<void>("/experiments/explanation-exposures", {
      method: "POST",
      body: JSON.stringify({ prediction_id: predictionId }),
    });
  }

  monitoringStatus(): Promise<DriftStatus> {
    return this.request<DriftStatus>("/monitoring/status");
  }

  monitoringHistory(limit = 60): Promise<{ snapshots: MonitoringSnapshot[] }> {
    return this.request<{ snapshots: MonitoringSnapshot[] }>(`/monitoring/history?limit=${limit}`);
  }

  evaluateFeatureDrift(
    referenceRows: Record<string, unknown>[],
    currentRows: Record<string, unknown>[],
    alpha = 0.01,
  ): Promise<DriftStatus> {
    return this.request<DriftStatus>("/monitoring/feature-drift", {
      method: "POST",
      body: JSON.stringify({ reference_rows: referenceRows, current_rows: currentRows, alpha }),
    });
  }

  retrainingTickets(): Promise<RetrainingTicket[]> {
    return this.request<RetrainingTicket[]>("/retraining-tickets");
  }

  createRetrainingTicket(reason: string): Promise<RetrainingTicket> {
    return this.request<RetrainingTicket>("/retraining-tickets", {
      method: "POST",
      body: JSON.stringify({ reason, human_review_confirmed: true }),
    });
  }
}

export const apiClient = new ApiClient();
