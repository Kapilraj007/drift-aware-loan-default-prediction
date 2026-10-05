import { ArrowRightOutlined, FileSearchOutlined, PlusOutlined, WarningOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Col, Progress, Row, Space, Statistic, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useNavigate } from "react-router-dom";
import { apiClient } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { formatDate, formatPercent } from "../lib/format";
import type { ApplicationResponse } from "../types";
import { DriftStatusTag, EmptyAction, PageIntro, PageSkeleton, QueryError, RiskTag } from "../components/Page";

const columns: ColumnsType<ApplicationResponse> = [
  { title: "Reference", dataIndex: "external_reference", render: (value: string | null, row) => value || row.id.slice(0, 8).toUpperCase() },
  { title: "Created", dataIndex: "created_at", render: formatDate },
  { title: "Risk", dataIndex: "risk_flag", render: (value: boolean | null) => value === null || value === undefined ? "Not scored" : <RiskTag flagged={value} /> },
  { title: "Status", dataIndex: "status", render: (value: string | undefined) => value ?? "Created" },
];

export function DashboardPage() {
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const summary = useQuery({ queryKey: ["dashboard", "summary"], queryFn: ({ signal }) => apiClient.dashboardSummary(signal) });
  if (summary.isPending) return <><PageIntro title="Dashboard" purpose="See the work that needs attention and choose the next safe action." /><PageSkeleton /></>;
  if (summary.isError) return <><PageIntro title="Dashboard" purpose="See the work that needs attention and choose the next safe action." /><QueryError error={summary.error} onRetry={() => void summary.refetch()} /></>;

  const data = summary.data;
  const awaiting = data.awaiting_decision ?? data.pending;
  const distribution = data.score_distribution ?? [];
  return (
    <>
      <PageIntro title="Dashboard" purpose="See the work that needs attention and choose the next safe action." extra={<Button onClick={() => void summary.refetch()}>Refresh</Button>} />
      <Typography.Text type="secondary">Last updated {formatDate(summary.dataUpdatedAt ? new Date(summary.dataUpdatedAt).toISOString() : undefined)} · refreshes only when you ask.</Typography.Text>
      <Row gutter={[16, 16]} className="metric-grid">
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="Applications" value={data.applications} /></Card></Col>
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="Awaiting decision" value={awaiting} /></Card></Col>
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="Risk-flag rate" value={(data.risk_flag_rate ?? 0) * 100} precision={1} suffix="%" /></Card></Col>
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="Override rate" value={(data.override_rate ?? 0) * 100} precision={1} suffix="%" /></Card></Col>
      </Row>

      <Row gutter={[16, 16]} className="section-row">
        <Col xs={24} xl={15}>
          <Card title="Risk-score distribution" extra={<Typography.Text type="secondary">Recent scored applications</Typography.Text>}>
            {distribution.length ? (
              <div className="chart-container" role="img" aria-label="Distribution of recent default risk scores">
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={distribution.map((item) => ({ ...item, bucket: item.bucket ?? `${Math.round((item.minimum ?? 0) * 100)}–${Math.round((item.maximum ?? 0) * 100)}%` }))}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="bucket" /><YAxis allowDecimals={false} /><Tooltip /><Bar dataKey="count" fill="#174ea6" name="Applications" radius={[4, 4, 0, 0]} /></BarChart>
                </ResponsiveContainer>
              </div>
            ) : <EmptyAction description="Score an application to begin the distribution." action={hasPermission("application:create") ? () => navigate("/applications/new") : undefined} actionLabel="New application" />}
          </Card>
        </Col>
        <Col xs={24} xl={9}>
          <Card title="Portfolio signals" className="signal-card">
            <Space direction="vertical" size="large" className="full-width">
              <div><Typography.Text strong>Drift detector</Typography.Text><div><DriftStatusTag status={data.drift_status?.status ?? data.latest_drift_status} /></div></div>
              <div><Typography.Text strong>Decisions completed</Typography.Text><Progress percent={data.scored ? Math.round((data.decided / data.scored) * 100) : 0} format={() => `${data.decided} of ${data.scored}`} /></div>
              <div><Typography.Text strong>Agreement with model</Typography.Text><div>{formatPercent(data.agreement_rate)}</div></div>
              <div><Typography.Text strong>Open retraining reviews</Typography.Text><div>{data.open_tickets}</div></div>
            </Space>
          </Card>
        </Col>
      </Row>

      <Card title="What to do next" className="next-actions">
        <Row gutter={[16, 16]}>
          {hasPermission("application:create") ? <Col xs={24} lg={8}><Card size="small"><PlusOutlined /><Typography.Title level={4}>Score a new application</Typography.Title><Typography.Paragraph>Enter applicant data, verify it, and request a model score.</Typography.Paragraph><Button type="link" onClick={() => navigate("/applications/new")}>Start review <ArrowRightOutlined /></Button></Card></Col> : null}
          <Col xs={24} lg={8}><Card size="small"><FileSearchOutlined /><Typography.Title level={4}>{awaiting} need a decision</Typography.Title><Typography.Paragraph>Open the review queue and record qualified human judgment.</Typography.Paragraph><Button type="link" onClick={() => navigate("/applications")}>Open applications <ArrowRightOutlined /></Button></Card></Col>
          {hasPermission("monitoring:read") ? <Col xs={24} lg={8}><Card size="small"><WarningOutlined /><Typography.Title level={4}>Review drift signals</Typography.Title><Typography.Paragraph>Inspect detector status and feature-level KS results before opening a ticket.</Typography.Paragraph><Button type="link" onClick={() => navigate("/monitoring")}>Open monitoring <ArrowRightOutlined /></Button></Card></Col> : null}
        </Row>
      </Card>

      <Card title="Recent applications" className="section-row">
        {data.recent_applications?.length ? <Table rowKey="id" columns={columns} dataSource={data.recent_applications} pagination={false} onRow={(row) => ({ onClick: () => navigate(`/applications/${row.id}`), className: "clickable-row" })} /> : <EmptyAction description="No applications are available yet." action={hasPermission("application:create") ? () => navigate("/applications/new") : undefined} actionLabel="Create the first application" />}
      </Card>
    </>
  );
}
