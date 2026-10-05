import { expect, test } from "@playwright/test";

const requested = process.env.E2E_REAL_STACK === "true";
const testDatabaseUrl = process.env.TEST_DATABASE_URL ?? "";

function databaseTarget(value: string): string {
  const parsed = new URL(value);
  return `${parsed.hostname.replace("-pooler", "")}/${parsed.pathname.replace(/^\//, "")}`;
}

if (requested) {
  if (!testDatabaseUrl) {
    throw new Error("E2E_REAL_STACK requires TEST_DATABASE_URL for an isolated migrated test branch.");
  }
  if (new URL(testDatabaseUrl).hostname.includes("-pooler")) {
    throw new Error("TEST_DATABASE_URL must be a direct endpoint, not a pooled endpoint.");
  }
  const testTarget = databaseTarget(testDatabaseUrl);
  for (const name of ["DATABASE_URL", "DIRECT_DATABASE_URL"] as const) {
    const configured = process.env[name];
    if (configured && databaseTarget(configured) === testTarget) {
      throw new Error("Refusing E2E: the isolated test target matches a showcase database target.");
    }
  }
}

const credentials = {
  admin: {
    username: process.env.E2E_ADMIN_USERNAME ?? "admin",
    password: process.env.E2E_ADMIN_PASSWORD ?? "Admin@Demo2026",
  },
  analyst: {
    username: process.env.E2E_ANALYST_USERNAME ?? "analyst",
    password: process.env.E2E_ANALYST_PASSWORD ?? "Analyst@Demo2026",
  },
  explain: {
    username: process.env.E2E_EXPLAIN_USERNAME ?? "officer.explain",
    password: process.env.E2E_EXPLAIN_PASSWORD ?? "Officer1@Demo2026",
  },
  scoreOnly: {
    username: process.env.E2E_SCORE_ONLY_USERNAME ?? "officer.scoreonly",
    password: process.env.E2E_SCORE_ONLY_PASSWORD ?? "Officer2@Demo2026",
  },
};

async function login(page: import("@playwright/test").Page, account: { username: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(account.username);
  await page.getByLabel("Password").fill(account.password);
  await page.getByRole("button", { name: /sign in securely/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function sessionToken(page: import("@playwright/test").Page): Promise<string> {
  return page.evaluate(() => {
    const raw = sessionStorage.getItem("drift-loan-session");
    if (!raw) throw new Error("Authenticated session was not persisted.");
    return (JSON.parse(raw) as { token: string }).token;
  });
}

test.describe.serial("real-stack Phase 8 acceptance", () => {
  test.skip(!requested, "Set E2E_REAL_STACK=true with an isolated TEST_DATABASE_URL and a running API/UI stack.");

  for (const role of [
    { name: "explanation officer", account: credentials.explain, visible: ["Dashboard", "New application", "Applications"], hidden: ["Monitoring", "Users"] },
    { name: "score-only officer", account: credentials.scoreOnly, visible: ["Dashboard", "New application", "Applications"], hidden: ["Monitoring", "Users"] },
    { name: "risk analyst", account: credentials.analyst, visible: ["Monitoring", "Retraining reviews", "Model card", "Study results"], hidden: ["Users", "Audit log"] },
    { name: "administrator", account: credentials.admin, visible: ["Users", "Roles & permissions", "Audit log"], hidden: [] },
  ]) {
    test(`${role.name} logs in and sees only permitted navigation`, async ({ page }) => {
      await login(page, role.account);
      for (const label of role.visible) {
        await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
      }
      for (const label of role.hidden) {
        await expect(page.getByText(label, { exact: true })).toHaveCount(0);
      }
    });
  }

  test("officer creates, scores, decides, and finds the application", async ({ page }) => {
    await login(page, credentials.explain);
    await page.getByText("New application", { exact: true }).first().click();
    await page.getByRole("button", { name: "Load sample" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: /create and score application/i }).click();
    await expect(page).toHaveURL(/\/applications\/[0-9a-f-]+$/i);
    const applicationUrl = page.url();
    await expect(page.getByText("Risk assessment")).toBeVisible();
    await page.getByRole("radio", { name: "Yes" }).click();
    await page.getByRole("button", { name: "Review decision" }).click();
    await page.getByRole("button", { name: "Record decision" }).click();
    await expect(page.getByText(/Decision recorded:/)).toBeVisible();
    await page.getByText("Applications", { exact: true }).first().click();
    await expect(page.locator(".ant-table-tbody tr").first()).toBeVisible();
    await page.goto("/dashboard");
    await expect(page.getByText("Recent applications")).toBeVisible();
    expect(applicationUrl).toContain("/applications/");
  });

  test("explanation response is present only for the explanation-shown officer", async ({ page }) => {
    await login(page, credentials.explain);
    await page.goto("/applications");
    const explainResponse = page.waitForResponse((response) => response.request().method() === "GET" && /\/applications\/[^/]+\/review/.test(response.url()));
    await page.locator(".ant-table-tbody tr").first().click();
    const explainBody = await (await explainResponse).json();
    expect(explainBody.latest_prediction.explanation.available).toBe(true);
    expect(explainBody.latest_prediction.explanation.top_features.length).toBeGreaterThan(0);
    await expect(page.getByText("Why the model produced this score")).toBeVisible();

    await page.evaluate(() => sessionStorage.clear());
    await page.goto("/login");
    await page.reload();
    await login(page, credentials.scoreOnly);
    await page.goto("/applications");
    const scoreOnlyResponse = page.waitForResponse((response) => response.request().method() === "GET" && /\/applications\/[^/]+\/review/.test(response.url()));
    await page.locator(".ant-table-tbody tr").first().click();
    const scoreOnlyBody = await (await scoreOnlyResponse).json();
    expect(scoreOnlyBody.latest_prediction.explanation.available).toBe(false);
    expect(scoreOnlyBody.latest_prediction.explanation.top_features).toEqual([]);
    await expect(page.getByText("Explanation not included in this study view")).toBeVisible();
    await expect(page.getByText("Why the model produced this score")).toHaveCount(0);
  });

  test("an officer receives an ownership denial for another officer's application", async ({ page }) => {
    await login(page, credentials.explain);
    const explainToken = await sessionToken(page);
    const applications = await page.request.get("/api/v1/applications?limit=1", {
      headers: { Authorization: `Bearer ${explainToken}` },
    });
    expect(applications.ok()).toBe(true);
    const applicationId = (await applications.json()).items[0].id as string;

    await page.evaluate(() => sessionStorage.clear());
    await page.goto("/login");
    await page.reload();
    await login(page, credentials.scoreOnly);
    await page.goto(`/applications/${applicationId}`);
    await expect(page.getByText("You do not have access to this application")).toBeVisible();
  });

  test("analyst runs the sample KS check and opens a drift-backed ticket", async ({ page }) => {
    await login(page, credentials.analyst);
    await page.getByText("Monitoring", { exact: true }).first().click();
    await page.getByRole("button", { name: "Run KS check" }).click();
    await page.getByRole("button", { name: "Use sample cohorts" }).click();
    await expect(page.getByText(/Reference \(\d+ rows\)/)).toBeVisible();
    await page.getByRole("button", { name: "Run check" }).click();
    await expect(page.getByText(/feature\(s\) flagged/)).toBeVisible();
    await page.getByText("Retraining reviews", { exact: true }).first().click();
    await page.getByLabel("Evidence and reason").fill("E2E review of the drifted sample cohort.");
    await page.getByRole("button", { name: "Open review" }).click();
    await expect(page.getByText("E2E review of the drifted sample cohort.")).toBeVisible();
  });

  test("admin reviews a ticket, creates and deactivates a user, and the token is refused", async ({ page }) => {
    await login(page, credentials.admin);
    await page.getByText("Retraining reviews", { exact: true }).first().click();
    const openRow = page.locator(".ant-table-tbody tr").filter({ hasText: "Open" }).first();
    await openRow.getByRole("button", { name: "Approve" }).click();
    await page.getByLabel("Review note").fill("Approved for investigation by the E2E administrator.");
    await page.getByRole("button", { name: "Approve" }).last().click();
    await expect(page.getByText("Approved for investigation by the E2E administrator.")).toBeVisible();

    await page.getByText("Users", { exact: true }).first().click();
    const username = `e2e.user.${Date.now()}`;
    const password = "E2eUser@Test2026";
    await page.getByRole("button", { name: "Create user" }).click();
    await page.getByLabel("Username").last().fill(username);
    await page.getByLabel("Initial password").fill(password);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await page.getByPlaceholder("Search username, name, or email").fill(username);
    await page.getByPlaceholder("Search username, name, or email").press("Enter");
    const userRow = page.locator(".ant-table-tbody tr").filter({ hasText: username });
    await expect(userRow).toBeVisible();

    const loginResponse = await page.request.post("/api/v1/auth/login", {
      data: { username, password },
    });
    expect(loginResponse.ok()).toBe(true);
    const userToken = (await loginResponse.json()).access_token as string;
    await userRow.getByRole("button", { name: "Deactivate" }).click();
    await page.getByRole("button", { name: "Deactivate", exact: true }).last().click();
    await expect(userRow.getByText("Inactive")).toBeVisible();
    const me = await page.request.get("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${userToken}` },
    });
    expect(me.status()).toBe(401);
  });

  test("session expiry redirects cleanly to login", async ({ page }) => {
    await login(page, credentials.explain);
    await page.route("**/api/v1/dashboard/summary", async (route) => {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ error: "authentication_required", detail: "Token expired" }),
      });
    });
    await page.getByRole("button", { name: "Refresh" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText("Your session expired. Please sign in again.")).toBeVisible();
  });

  test("invalid application data returns field-level 422, never model 503", async ({ page }) => {
    await login(page, credentials.explain);
    const token = await sessionToken(page);
    const response = await page.request.post("/api/v1/applications", {
      headers: { Authorization: `Bearer ${token}` },
      data: { features: { annual_inc: "not-a-number" } },
    });
    expect(response.status()).toBe(422);
    const body = await response.json();
    expect(body.error).toBe("validation_error");
    expect(body.detail.some((item: { field?: string }) => item.field?.startsWith("features."))).toBe(true);
  });
});
