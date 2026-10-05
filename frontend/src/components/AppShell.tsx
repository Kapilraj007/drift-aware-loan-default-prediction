import {
  AppstoreOutlined,
  AuditOutlined,
  BankOutlined,
  BookOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MonitorOutlined,
  PlusCircleOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Breadcrumb, Button, Dropdown, Grid, Layout, Menu, Modal, Space, Tag, Tour, Typography } from "antd";
import type { MenuProps, TourProps } from "antd";
import { useMemo, useRef, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { apiClient } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { titleCase } from "../lib/format";
import type { Permission } from "../types";
import { DriftStatusTag } from "./Page";

const { Header, Sider, Content, Footer } = Layout;

interface NavigationItem {
  key: string;
  label: string;
  icon: React.ReactNode;
  permissions?: readonly Permission[];
}

const groups: Array<{ key: string; label: string; children: NavigationItem[] }> = [
  { key: "overview", label: "Overview", children: [
    { key: "/dashboard", label: "Dashboard", icon: <DashboardOutlined />, permissions: ["dashboard:read"] },
  ] },
  { key: "loan-review", label: "Loan review", children: [
    { key: "/applications/new", label: "New application", icon: <PlusCircleOutlined />, permissions: ["application:create"] },
    { key: "/applications", label: "Applications", icon: <FileSearchOutlined />, permissions: ["application:read_own", "application:read_all"] },
  ] },
  { key: "risk-model", label: "Risk & model", children: [
    { key: "/monitoring", label: "Monitoring", icon: <MonitorOutlined />, permissions: ["monitoring:read"] },
    { key: "/retraining", label: "Retraining reviews", icon: <ExperimentOutlined />, permissions: ["retraining:read"] },
    { key: "/model", label: "Model card", icon: <BankOutlined />, permissions: ["model:read"] },
    { key: "/study", label: "Study results", icon: <AppstoreOutlined />, permissions: ["experiment:read_results"] },
  ] },
  { key: "administration", label: "Administration", children: [
    { key: "/users", label: "Users", icon: <TeamOutlined />, permissions: ["user:manage"] },
    { key: "/roles", label: "Roles & permissions", icon: <SafetyCertificateOutlined />, permissions: ["role:read"] },
    { key: "/audit", label: "Audit log", icon: <AuditOutlined />, permissions: ["audit:read"] },
  ] },
  { key: "help", label: "Help", children: [
    { key: "/how-it-works", label: "How it works", icon: <BookOutlined /> },
  ] },
];

function breadcrumbItems(pathname: string): Array<{ title: React.ReactNode }> {
  const segments = pathname.split("/").filter(Boolean);
  const names: Record<string, string> = {
    dashboard: "Dashboard", applications: "Applications", new: "New application",
    monitoring: "Monitoring", retraining: "Retraining reviews", model: "Model card",
    study: "Study results", users: "Users", roles: "Roles & permissions", audit: "Audit log",
    profile: "Profile", "how-it-works": "How it works",
  };
  return [{ title: <Link to="/dashboard">Home</Link> }, ...segments.map((segment, index) => ({
    title: index === segments.length - 1
      ? (names[segment] ?? (segments[0] === "applications" ? "Application review" : titleCase(segment)))
      : <Link to={`/${segments.slice(0, index + 1).join("/")}`}>{names[segment] ?? titleCase(segment)}</Link>,
  }))];
}

export function AppShell() {
  const { user, hasPermission, signOut, databaseWaking } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const screens = Grid.useBreakpoint();
  const [collapsed, setCollapsed] = useState(false);
  const tourKey = `drift-loan-tour-${user?.id ?? "anonymous"}`;
  const [welcomeOpen, setWelcomeOpen] = useState(() => sessionStorage.getItem(tourKey) !== "done");
  const [tourOpen, setTourOpen] = useState(false);
  const navigationRef = useRef<HTMLDivElement>(null);
  const statusRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  const menuItems = useMemo<MenuProps["items"]>(() => groups.flatMap((group) => {
    const children: NonNullable<MenuProps["items"]> = group.children
      .filter((item) => !item.permissions || hasPermission(item.permissions))
      .map(({ key, label, icon }) => ({ key, label, icon }));
    return children.length ? [{ type: "group" as const, key: group.key, label: group.label, children }] : [];
  }), [hasPermission]);

  const canReadModel = hasPermission("model:read");
  const canReadMonitoring = hasPermission("monitoring:read");
  const modelQuery = useQuery({ queryKey: ["model", "shell"], queryFn: ({ signal }) => apiClient.model(signal), enabled: canReadModel, staleTime: 5 * 60_000 });
  const driftQuery = useQuery({ queryKey: ["monitoring", "status"], queryFn: ({ signal }) => apiClient.monitoringStatus(signal), enabled: canReadMonitoring, staleTime: 60_000 });
  const syntheticDemo = import.meta.env.VITE_SYNTHETIC_DEMO === "true"
    || Boolean(modelQuery.data?.synthetic_demo)
    || modelQuery.data?.metadata.synthetic_demo === true;

  const userMenu: MenuProps["items"] = [
    { key: "profile", icon: <UserOutlined />, label: "Profile" },
    { key: "signout", icon: <SettingOutlined />, label: "Sign out", danger: true },
  ];
  const closeWelcome = (startTour: boolean) => {
    sessionStorage.setItem(tourKey, "done");
    setWelcomeOpen(false);
    setTourOpen(startTour);
  };
  const tourSteps: TourProps["steps"] = [
    { title: "Role-aware navigation", description: "Only the work your account is allowed to perform appears here.", target: () => navigationRef.current ?? document.body },
    { title: "Model and drift context", description: "These chips show live status when your permissions allow it.", target: () => statusRef.current ?? document.body },
    { title: "A clear next step", description: "Every page explains its purpose and provides a safe path forward.", target: () => contentRef.current ?? document.body },
  ];

  return (
    <Layout className="corporate-shell">
      <Sider
        className="app-sider"
        width={256}
        collapsible
        collapsed={collapsed || !screens.lg}
        trigger={null}
        breakpoint="lg"
        aria-label="Primary navigation"
      >
        <div className="brand" ref={navigationRef}>
          <BankOutlined aria-hidden />
          {collapsed || !screens.lg ? null : <span><strong>DriftAware</strong><small>Credit review</small></span>}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          items={menuItems}
          selectedKeys={[location.pathname === "/applications/new" ? location.pathname : `/${location.pathname.split("/")[1]}`]}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header className="app-header">
          <div className="header-left">
            {screens.lg ? <Button type="text" aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed((value) => !value)} /> : null}
            <Breadcrumb items={breadcrumbItems(location.pathname)} />
          </div>
          <Space className="header-status" ref={statusRef} wrap>
            {databaseWaking ? <Tag color="processing">Database waking — retrying</Tag> : null}
            {canReadModel ? <Tag color={modelQuery.isError ? "error" : "blue"}>{modelQuery.data ? `Model ${modelQuery.data.model_version}` : modelQuery.isError ? "Model unavailable" : "Model loading"}</Tag> : <Tag>Model status restricted</Tag>}
            {canReadMonitoring ? <DriftStatusTag status={driftQuery.data?.status} /> : <Tag>Drift status restricted</Tag>}
            <Dropdown menu={{ items: userMenu, onClick: ({ key }) => key === "signout" ? signOut() : navigate("/profile") }} placement="bottomRight">
              <Button type="text" className="user-button" icon={<UserOutlined />}>
                <span>{user?.full_name || user?.username}</span><small>{user ? titleCase(user.role) : ""}</small>
              </Button>
            </Dropdown>
          </Space>
        </Header>
        {syntheticDemo ? <Alert className="synthetic-banner" banner showIcon type="warning" message="Demo model trained on synthetic data — metrics shown here are not research results." /> : null}
        <Content className="app-content" ref={contentRef}>
          <Outlet />
        </Content>
        <Footer className="app-footer">Decision support only · A qualified human makes the final lending decision.</Footer>
      </Layout>
      <Modal open={welcomeOpen} title="Welcome to DriftAware" onCancel={() => closeWelcome(false)} footer={[
        <Button key="skip" onClick={() => closeWelcome(false)}>Skip tour</Button>,
        <Button key="start" type="primary" onClick={() => closeWelcome(true)}>Take a quick tour</Button>,
      ]}>
        <Typography.Paragraph>Follow an application from scoring through a human decision, then use monitoring and retraining review to manage model risk.</Typography.Paragraph>
      </Modal>
      <Tour open={tourOpen} onClose={() => setTourOpen(false)} steps={tourSteps} />
    </Layout>
  );
}
