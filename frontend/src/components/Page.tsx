import { Alert, Button, Empty, Skeleton, Tag, Typography } from "antd";
import { CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined, WarningOutlined } from "@ant-design/icons";
import type { ReactNode } from "react";
import type { DetectorStatus } from "../types";

export function PageIntro({ title, purpose, extra }: { title: string; purpose: string; extra?: ReactNode }) {
  return (
    <header className="page-intro">
      <div><Typography.Title level={2}>{title}</Typography.Title><Typography.Paragraph>{purpose}</Typography.Paragraph></div>
      {extra ? <div className="page-actions">{extra}</div> : null}
    </header>
  );
}

export function PageSkeleton() {
  return <div role="status" aria-label="Loading page"><Skeleton active paragraph={{ rows: 7 }} /></div>;
}

export function QueryError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "The information could not be loaded.";
  return <Alert type="error" showIcon message="Unable to load this page" description={message} action={onRetry ? <Button onClick={onRetry}>Try again</Button> : undefined} />;
}

export function EmptyAction({ description, action, actionLabel }: { description: string; action?: () => void; actionLabel?: string }) {
  return <Empty description={description}>{action && actionLabel ? <Button type="primary" onClick={action}>{actionLabel}</Button> : null}</Empty>;
}

export function DriftStatusTag({ status }: { status: DetectorStatus | null | undefined }) {
  if (status === "drift_detected") return <Tag icon={<WarningOutlined />} color="error">Drift detected</Tag>;
  if (status === "stable") return <Tag icon={<CheckCircleOutlined />} color="success">Stable</Tag>;
  if (status === "watch") return <Tag icon={<ExclamationCircleOutlined />} color="warning">Watch</Tag>;
  return <Tag icon={<ClockCircleOutlined />}>No data yet</Tag>;
}

export function RiskTag({ flagged }: { flagged: boolean | null | undefined }) {
  return flagged
    ? <Tag icon={<WarningOutlined />} color="error">Above threshold</Tag>
    : <Tag icon={<CheckCircleOutlined />} color="success">Below threshold</Tag>;
}

export function DecisionSupportNotice() {
  return <Alert className="decision-support-notice" type="info" showIcon message="Decision support only" description="A qualified human makes and records the final lending decision." />;
}
