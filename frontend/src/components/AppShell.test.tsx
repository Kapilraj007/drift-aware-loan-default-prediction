import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  user: {
    id: "officer-1",
    username: "officer.explain",
    full_name: "Demo Officer",
    role: "loan_officer",
  },
  permissions: ["application:create", "application:read_own", "dashboard:read"],
  hasPermission: (permission: string | readonly string[]) => {
    const wanted = Array.isArray(permission) ? permission : [permission];
    return wanted.some((item) => auth.permissions.includes(item));
  },
  signOut: vi.fn(),
  databaseWaking: false,
}));

vi.mock("../context/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../api/client", () => ({
  apiClient: {
    model: vi.fn(),
    monitoringStatus: vi.fn(),
  },
}));

import { AppShell } from "./AppShell";

describe("AppShell permission navigation", () => {
  it("shows officer work and hides administration and monitoring links", async () => {
    sessionStorage.setItem("drift-loan-tour-officer-1", "done");
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/dashboard"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <Routes>
              <Route element={<AppShell />}>
                <Route path="/dashboard" element={<div>Dashboard body</div>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </AntApp>,
    );

    expect(await screen.findByText("New application")).toBeInTheDocument();
    expect(screen.getByText("Applications")).toBeInTheDocument();
    expect(screen.queryByText("Users")).not.toBeInTheDocument();
    expect(screen.queryByText("Monitoring")).not.toBeInTheDocument();
  });
});
