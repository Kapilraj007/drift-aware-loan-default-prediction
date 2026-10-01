import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./client";

describe("ApiClient", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends a bearer token and request body to the application API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "app-1" }), { headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient("/api/v1");
    client.setToken("jwt-token");

    await client.createApplication(null, {
      annual_inc: null, dti: null, revol_util: null, revol_bal: null, open_acc: null, total_acc: null,
      delinq_2yrs: null, inq_last_6mths: null, loan_amnt: null, term: null, int_rate: null,
      installment: null, grade: null, sub_grade: null, purpose: null, emp_length: null,
      home_ownership: null, earliest_cr_line: null, issue_d: "Jan-2018",
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/applications", expect.objectContaining({ method: "POST" }));
    const request = fetchMock.mock.calls[0][1];
    expect(new Headers(request?.headers).get("Authorization")).toBe("Bearer jwt-token");
  });

  it("surfaces API details for non-successful responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Application access is denied" }), {
          status: 403,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    const client = new ApiClient("/api/v1");
    await expect(client.currentUser()).rejects.toMatchObject({
      status: 403,
      detail: "Application access is denied",
    });
  });
});
