import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ApiClient } from "./client";

const server = setupServer(
  http.get("http://api.test/api/v1/auth/me", () => HttpResponse.json({
    id: "user-1",
    username: "officer.explain",
    role: "loan_officer",
    permissions: ["dashboard:read"],
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
  })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("ApiClient with MSW", () => {
  it("consumes the real JSON contract shape through the shared request path", async () => {
    const user = await new ApiClient("http://api.test/api/v1").currentUser();
    expect(user).toMatchObject({ username: "officer.explain", role: "loan_officer" });
  });
});
