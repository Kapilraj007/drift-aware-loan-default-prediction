import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  Upload,
} from "antd";
import type { UploadProps } from "antd";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ApiError, apiClient } from "../api/client";
import {
  DriftStatusTag,
  EmptyAction,
  PageIntro,
  PageSkeleton,
  QueryError,
} from "../components/Page";
import { useAuth } from "../context/AuthContext";
import { parseCohortFile, parseDelimitedRows } from "../lib/csv";
import { formatDate, formatPercent, titleCase } from "../lib/format";
import type { RetrainingTicket } from "../types";

type Cohort = Record<string, unknown>[];

function CohortPreview({ label, rows }: { label: string; rows: Cohort }) {
  const keys = Object.keys(rows[0] ?? {}).slice(0, 5);
  return <Card size="small" title={`${label} (${rows.length} rows)`}>
    {rows.length ? <Table
      size="small"
      rowKey="__row"
      pagination={false}
      scroll={{ x: true }}
      dataSource={rows.slice(0, 4).map((row, index) => ({ ...row, __row: index }))}
      columns={keys.map((key) => ({
        title: titleCase(key),
        dataIndex: key,
        ellipsis: true,
        render: (value: unknown) => String(value ?? ""),
      }))}
    /> : <Typography.Text type="secondary">No cohort loaded.</Typography.Text>}
  </Card>;
}

export function MonitoringPage() {
  const { hasPermission } = useAuth();
  const { message } = AntApp.useApp();
  const client = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [referenceRows, setReferenceRows] = useState<Cohort>([]);
  const [currentRows, setCurrentRows] = useState<Cohort>([]);
  const status = useQuery({
    queryKey: ["monitoring", "status"],
    queryFn: ({ signal }) => apiClient.monitoringStatus(signal),
  });
  const history = useQuery({
    queryKey: ["monitoring", "history"],
    queryFn: ({ signal }) => apiClient.monitoringHistory(60, signal),
  });
  const check = useMutation({
    mutationFn: () => apiClient.evaluateFeatureDrift(referenceRows, currentRows),
    onSuccess: async (result) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["monitoring", "status"] }),
        client.invalidateQueries({ queryKey: ["monitoring", "history"] }),
      ]);
      message.success(`KS check complete: ${result.feature_drift_count} feature(s) flagged.`);
    },
  });

  const upload = (
    label: string,
    setter: (rows: Cohort) => void,
  ): UploadProps => ({
    accept: ".csv,.json",
    showUploadList: false,
    beforeUpload: async (file) => {
      try {
        const rows = await parseCohortFile(file);
        setter(rows);
        message.success(`${label} loaded: ${rows.length} rows.`);
      } catch (error) {
        message.error(error instanceof Error ? error.message : `${label} could not be read.`);
      }
      return Upload.LIST_IGNORE;
    },
  });
  const loadSampleCohorts = async () => {
    try {
      const [referenceResponse, currentResponse] = await Promise.all([
        fetch("/reference_cohort.csv"),
        fetch("/current_cohort_drifted.csv"),
      ]);
      if (!referenceResponse.ok || !currentResponse.ok) {
        throw new Error("Sample cohort files are unavailable. Run the demo preparation command.");
      }
      const [referenceText, currentText] = await Promise.all([
        referenceResponse.text(),
        currentResponse.text(),
      ]);
      setReferenceRows(parseDelimitedRows(referenceText));
      setCurrentRows(parseDelimitedRows(currentText));
      message.success("Sample reference and drifted cohorts loaded.");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "Sample cohorts could not be loaded.");
    }
  };

  if (status.isPending) return <PageSkeleton />;
  if (status.isError) {
    return <QueryError error={status.error} onRetry={() => void status.refetch()} />;
  }
  const data = status.data;
  const trend = history.data?.snapshots.map((item) => ({
    observed: formatDate(item.created_at),
    drifting: item.snapshot.feature_drift_count,
    scores: item.snapshot.score_stream_count,
  })) ?? [];
  const statusMeaning = data.status === "drift_detected"
    ? "One or more persisted detectors found a material distribution change. Review the evidence before opening a retraining ticket."
    : data.status === "not_observed"
      ? "No detector evidence has been recorded yet. Run a cohort check or score applications."
      : "No currently persisted detector is signalling drift.";

  return <>
    <PageIntro
      title="Monitoring"
      purpose="Inspect persisted score and feature-drift signals; checks refresh only when you ask."
      extra={<Space>
        <Button onClick={() => {
          void status.refetch();
          void history.refetch();
        }}>Refresh</Button>
        {hasPermission("monitoring:run_check")
          ? <Button type="primary" onClick={() => setDrawerOpen(true)}>Run KS check</Button>
          : null}
      </Space>}
    />
    <Typography.Text type="secondary">
      Last updated {formatDate(data.updated_at)}. This page does not poll in the background.
    </Typography.Text>
    <Alert className="section-row" type={data.status === "drift_detected" ? "warning" : "info"} showIcon message={<DriftStatusTag status={data.status} />} description={statusMeaning} />
    <Row gutter={[16, 16]} className="section-row">
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="Detector status" valueRender={() => <DriftStatusTag status={data.status} />} /></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="ADWIN alert" value={data.adwin_change_detected ? "Detected" : "Not detected"} /></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="Observed scores" value={data.score_stream_count} /></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="Features with drift" value={data.feature_drift_count} /></Card></Col>
    </Row>
    <Card className="section-row" title="Feature drift results" extra={<Typography.Text type="secondary">Drift when p-value is below 0.01</Typography.Text>}>
      {data.feature_results.length ? <Table
        rowKey="feature"
        pagination={false}
        dataSource={data.feature_results}
        columns={[
          { title: "Feature", dataIndex: "feature", render: titleCase },
          { title: "KS statistic", dataIndex: "statistic", render: (value: number) => value.toFixed(3) },
          { title: "p-value", dataIndex: "p_value", render: (value: number) => value.toFixed(4) },
          { title: "Reference rows", dataIndex: "reference_count" },
          { title: "Current rows", dataIndex: "current_count" },
          { title: "Result", dataIndex: "drift_detected", render: (value: boolean) => <Tag color={value ? "error" : "success"}>{value ? "Drift detected" : "Stable"}</Tag> },
        ]}
      /> : <EmptyAction description="No feature-drift result has been persisted yet." action={hasPermission("monitoring:run_check") ? () => setDrawerOpen(true) : undefined} actionLabel="Run the first check" />}
    </Card>
    <Row className="section-row" gutter={[16, 16]}>
      <Col xs={24} xl={14}>
        <Card title="Detector trend">
          {trend.length ? <ResponsiveContainer width="100%" height={260}>
            <LineChart data={trend}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="observed" hide={trend.length > 12} />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Line type="monotone" dataKey="drifting" name="Drifting features" stroke="#c62828" isAnimationActive={false} />
              <Line type="monotone" dataKey="scores" name="Scores observed" stroke="#174ea6" isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer> : <EmptyAction description="No monitoring trend is available." />}
        </Card>
      </Col>
      <Col xs={24} xl={10}>
        <Card title="Recent detector snapshots">
          {history.data?.snapshots.length ? <Table
            size="small"
            rowKey="id"
            pagination={{ pageSize: 6 }}
            dataSource={[...history.data.snapshots].reverse()}
            columns={[
              { title: "Observed", dataIndex: "created_at", render: formatDate },
              { title: "Source", dataIndex: "source", render: titleCase },
              { title: "Status", render: (_, row) => <DriftStatusTag status={row.snapshot.status} /> },
            ]}
          /> : <EmptyAction description="No monitoring history is available." />}
        </Card>
      </Col>
    </Row>
    <Drawer
      width={760}
      open={drawerOpen}
      title="Run a feature-level KS check"
      onClose={() => setDrawerOpen(false)}
      extra={<Button
        type="primary"
        disabled={referenceRows.length < 2 || currentRows.length < 2}
        loading={check.isPending}
        onClick={() => check.mutate()}
      >Run check</Button>}
    >
      <Alert type="info" showIcon message="Compare like-for-like cohorts" description="The two files must share numeric feature columns and contain at least two rows. Raw cohort rows are evaluated in memory and are not persisted." />
      <Space className="section-row" wrap>
        <Upload {...upload("Reference cohort", setReferenceRows)}><Button>Choose reference file</Button></Upload>
        <Upload {...upload("Current cohort", setCurrentRows)}><Button>Choose current file</Button></Upload>
        <Button onClick={() => void loadSampleCohorts()}>Use sample cohorts</Button>
      </Space>
      <Row className="section-row" gutter={[12, 12]}>
        <Col xs={24} md={12}><CohortPreview label="Reference" rows={referenceRows} /></Col>
        <Col xs={24} md={12}><CohortPreview label="Current" rows={currentRows} /></Col>
      </Row>
      {check.isSuccess ? <Alert className="section-row" type={check.data.status === "drift_detected" ? "warning" : "success"} showIcon message={`${check.data.feature_drift_count} feature(s) flagged`} description="The result is persisted and now appears on the monitoring page." /> : null}
      {check.isError ? <Alert className="section-row" type="error" showIcon message="KS check failed" description={check.error instanceof ApiError ? check.error.detail : "Check the cohort files and try again."} /> : null}
    </Drawer>
  </>;
}

export function RetrainingPage() {
  const { hasPermission } = useAuth();
  const { message } = AntApp.useApp();
  const client = useQueryClient();
  const [reason, setReason] = useState("");
  const [reviewTarget, setReviewTarget] = useState<{ ticket: RetrainingTicket; decision: "approve" | "reject" } | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const tickets = useQuery({
    queryKey: ["retraining-tickets"],
    queryFn: ({ signal }) => apiClient.retrainingTickets(signal),
  });
  const monitoring = useQuery({
    queryKey: ["monitoring", "status"],
    queryFn: ({ signal }) => apiClient.monitoringStatus(signal),
    enabled: hasPermission("retraining:create"),
  });
  const create = useMutation({
    mutationFn: () => apiClient.createRetrainingTicket(reason.trim()),
    onSuccess: () => {
      setReason("");
      message.success("Retraining review ticket opened.");
      void client.invalidateQueries({ queryKey: ["retraining-tickets"] });
    },
  });
  const review = useMutation({
    mutationFn: ({ id, decision, note }: { id: string; decision: "approve" | "reject"; note: string }) => apiClient.reviewRetrainingTicket(id, decision, note),
    onSuccess: () => {
      setReviewTarget(null);
      setReviewNote("");
      message.success("Ticket review recorded. No training was started.");
      void client.invalidateQueries({ queryKey: ["retraining-tickets"] });
    },
  });
  const driftDetected = monitoring.data?.status === "drift_detected";

  return <>
    <PageIntro title="Retraining reviews" purpose="Open a traceable human review when evidence warrants retraining; approval never starts training automatically." />
    <Alert type="info" showIcon message="Human governance checkpoint" description="Approving a ticket records authorization to investigate retraining. Model training and deployment remain separate, deliberate actions." />
    {hasPermission("retraining:create") ? <Card className="section-row" title="Open retraining review">
      {!driftDetected ? <Alert type="warning" showIcon message="A ticket requires detected drift" description="Run and review a monitoring check first. Ticket creation stays disabled until the persisted status is Drift detected." /> : null}
      <Form layout="vertical" className="section-row">
        <Form.Item label="Evidence and reason" required help="Describe the detector evidence and the human review requested.">
          <Input.TextArea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={2000} />
        </Form.Item>
        <Button type="primary" disabled={!driftDetected || !reason.trim()} loading={create.isPending} onClick={() => create.mutate()}>Open review</Button>
        {create.isError ? <Alert className="section-row" type="error" showIcon message="Ticket could not be opened" description={create.error instanceof ApiError ? create.error.detail : "Try again."} /> : null}
      </Form>
    </Card> : null}
    <Card className="section-row" title="Review queue">
      {tickets.isPending ? <PageSkeleton /> : tickets.isError ? <QueryError error={tickets.error} onRetry={() => void tickets.refetch()} /> : tickets.data.length ? <Table
        rowKey="id"
        dataSource={tickets.data}
        pagination={{ pageSize: 10 }}
        columns={[
          { title: "Created", dataIndex: "created_at", render: formatDate },
          { title: "Reason", dataIndex: "reason" },
          { title: "Status", dataIndex: "status", render: (value: string) => <Tag color={value === "open" ? "processing" : value === "approved" ? "success" : "error"}>{titleCase(value)}</Tag> },
          { title: "Review note", dataIndex: "review_note", render: (value: string | null) => value || "Not reviewed" },
          { title: "Action", render: (_, ticket) => hasPermission("retraining:review") && ticket.status === "open" ? <Space>
            <Button onClick={() => setReviewTarget({ ticket, decision: "approve" })}>Approve</Button>
            <Button danger onClick={() => setReviewTarget({ ticket, decision: "reject" })}>Reject</Button>
          </Space> : "No action" },
        ]}
      /> : <EmptyAction description="No retraining reviews have been opened." />}
    </Card>
    <Modal
      open={Boolean(reviewTarget)}
      title={`${reviewTarget ? titleCase(reviewTarget.decision) : "Review"} retraining ticket`}
      okText={reviewTarget ? titleCase(reviewTarget.decision) : "Save"}
      okButtonProps={{ danger: reviewTarget?.decision === "reject", disabled: !reviewNote.trim() }}
      confirmLoading={review.isPending}
      onCancel={() => {
        setReviewTarget(null);
        setReviewNote("");
      }}
      onOk={() => {
        if (reviewTarget && reviewNote.trim()) {
          review.mutate({ id: reviewTarget.ticket.id, decision: reviewTarget.decision, note: reviewNote.trim() });
        }
      }}
    >
      <Typography.Paragraph>Record the evidence behind this human review. This action does not run training.</Typography.Paragraph>
      <Input.TextArea aria-label="Review note" value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} maxLength={2000} />
      {review.isError ? <Alert className="section-row" type="error" showIcon message="Review could not be saved" description={review.error instanceof ApiError ? review.error.detail : "Try again."} /> : null}
    </Modal>
  </>;
}

export function ModelPage() {
  const model = useQuery({ queryKey: ["model"], queryFn: ({ signal }) => apiClient.model(signal) });
  const runs = useQuery({ queryKey: ["training-runs"], queryFn: ({ signal }) => apiClient.trainingRuns(signal) });
  if (model.isPending) return <PageSkeleton />;
  if (model.isError) return <QueryError error={model.error} onRetry={() => void model.refetch()} />;
  const data = model.data;
  return <>
    <PageIntro title="Model card" purpose="Review the deployed artifact, feature contract, and provenance before interpreting scores." />
    {data.synthetic_demo ? <Alert type="warning" showIcon message="Synthetic demo model" description="Metrics and predictions are for demonstration only and are not research results." /> : null}
    <Card className="section-row"><Descriptions column={{ xs: 1, md: 2 }} items={[
      { key: "version", label: "Model version", children: data.model_version },
      { key: "threshold", label: "Decision threshold", children: formatPercent(data.prediction_threshold) },
      { key: "features", label: "Feature count", children: data.feature_count },
      { key: "schema", label: "Feature schema checksum", children: <Typography.Text code>{data.feature_schema_sha256}</Typography.Text> },
      { key: "view", label: "Feature view", children: data.feature_view },
    ]} /></Card>
    <Card title="Training run provenance" className="section-row">
      {runs.data?.runs.length ? <Table
        rowKey={(row) => String(row.id ?? row.model_version ?? JSON.stringify(row))}
        dataSource={runs.data.runs}
        pagination={{ pageSize: 8 }}
        columns={Object.keys(runs.data.runs[0]).slice(0, 6).map((key) => ({
          title: titleCase(key),
          dataIndex: key,
          render: (value: unknown) => typeof value === "object" ? JSON.stringify(value) : String(value ?? "Not provided"),
        }))}
      /> : <EmptyAction description="No retained training-run records are available." />}
    </Card>
  </>;
}

export function StudyPage() {
  const summary = useQuery({
    queryKey: ["experiment-summary"],
    queryFn: ({ signal }) => apiClient.experimentSummary(signal),
  });
  if (summary.isPending) return <PageSkeleton />;
  if (summary.isError) {
    return <QueryError error={summary.error} onRetry={() => void summary.refetch()} />;
  }
  const arms = summary.data.arms;
  return <>
    <PageIntro title="Study results" purpose="Compare explanation arms with sample sizes visible and without claiming statistical significance." />
    <Row gutter={[16, 16]}>{arms.map((arm) => <Col xs={24} md={12} key={arm.variant}>
      <Card title={titleCase(arm.variant)}>
        <Statistic title="Exposures (n)" value={arm.exposures} />
        <Statistic title="Decisions" value={arm.decisions} />
        <Typography.Paragraph>Agreement: {formatPercent(arm.agreement_rate)} | Override: {formatPercent(arm.override_rate)}</Typography.Paragraph>
      </Card>
    </Col>)}</Row>
    <Card className="section-row" title="Decision comparison">
      <ResponsiveContainer width="100%" height={250}>
        <BarChart data={arms}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="variant" /><YAxis allowDecimals={false} /><Tooltip /><Bar dataKey="decisions" fill="#174ea6" isAnimationActive={false} /></BarChart>
      </ResponsiveContainer>
    </Card>
    <Alert className="section-row" type="info" showIcon message={summary.data.note || "Descriptive results only"} description="Small samples are reported with n. No significance or causal claim is made in this showcase." />
  </>;
}
