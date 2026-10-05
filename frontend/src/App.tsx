import { Result, Spin } from "antd";
import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { LoginPage } from "./components/LoginPage";
import { useAuth } from "./context/AuthContext";
import type { Permission } from "./types";
import {
  ApplicationReviewPage,
  ApplicationsPage,
  AuditPage,
  DashboardPage,
  ForbiddenPage,
  HowItWorksPage,
  ModelPage,
  MonitoringPage,
  NewApplicationPage,
  NotFoundPage,
  ProfilePage,
  RetrainingPage,
  RolesPage,
  StudyPage,
  UsersPage,
} from "./pages";

class RouteErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Route rendering failed", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.failed) {
      return <Result status="error" title="This page could not be displayed" subTitle="Refresh the page or return to the dashboard." />;
    }
    return this.props.children;
  }
}

function AuthenticatedRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return <main className="full-page-loader" role="status"><Spin size="large" /><span>Restoring your session…</span></main>;
  }
  return user ? <Outlet /> : <Navigate to="/login" replace state={{ from: location.pathname }} />;
}

function PublicOnlyRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <main className="full-page-loader" role="status"><Spin size="large" /></main>;
  return user ? <Navigate to="/dashboard" replace /> : children;
}

function PermissionRoute({ anyOf, children }: { anyOf: readonly Permission[]; children: ReactNode }) {
  const { hasPermission } = useAuth();
  return hasPermission(anyOf) ? children : <ForbiddenPage />;
}

export default function App() {
  return (
    <RouteErrorBoundary>
      <Routes>
        <Route path="/login" element={<PublicOnlyRoute><LoginPage /></PublicOnlyRoute>} />
        <Route element={<AuthenticatedRoute />}>
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<PermissionRoute anyOf={["dashboard:read"]}><DashboardPage /></PermissionRoute>} />
            <Route path="applications/new" element={<PermissionRoute anyOf={["application:create"]}><NewApplicationPage /></PermissionRoute>} />
            <Route path="applications" element={<PermissionRoute anyOf={["application:read_own", "application:read_all"]}><ApplicationsPage /></PermissionRoute>} />
            <Route path="applications/:applicationId" element={<PermissionRoute anyOf={["application:read_own", "application:read_all"]}><ApplicationReviewPage /></PermissionRoute>} />
            <Route path="monitoring" element={<PermissionRoute anyOf={["monitoring:read"]}><MonitoringPage /></PermissionRoute>} />
            <Route path="retraining" element={<PermissionRoute anyOf={["retraining:read"]}><RetrainingPage /></PermissionRoute>} />
            <Route path="model" element={<PermissionRoute anyOf={["model:read"]}><ModelPage /></PermissionRoute>} />
            <Route path="study" element={<PermissionRoute anyOf={["experiment:read_results"]}><StudyPage /></PermissionRoute>} />
            <Route path="users" element={<PermissionRoute anyOf={["user:manage"]}><UsersPage /></PermissionRoute>} />
            <Route path="roles" element={<PermissionRoute anyOf={["role:read"]}><RolesPage /></PermissionRoute>} />
            <Route path="audit" element={<PermissionRoute anyOf={["audit:read"]}><AuditPage /></PermissionRoute>} />
            <Route path="profile" element={<ProfilePage />} />
            <Route path="how-it-works" element={<HowItWorksPage />} />
            <Route path="403" element={<ForbiddenPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </RouteErrorBoundary>
  );
}
