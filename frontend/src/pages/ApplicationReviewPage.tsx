import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  Progress,
  Radio,
  Row,
  Space,
  Table,
  Timeline,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ApiError, apiClient } from "../api/client";
import {
  DecisionSupportNotice,
  EmptyAction,
  PageIntro,
  PageSkeleton,
  QueryError,
  RiskTag,
} from "../components/Page";
import { useAuth } from "../context/AuthContext";
import { formatDate, formatPercent, titleCase } from "../lib/format";
import type { OfficerDecision } from "../types";

export function ApplicationReviewPage() {
  const { applicationId = "" } = useParams();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuth();
  const { modal, message } = AntApp.useApp();
  const [decision, setDecision] = useState<OfficerDecision>("approve");
  const [note, setNote] = useState("");
  const [agreement, setAgreement] = useState<boolean | null>(null);
  const [amending, setAmending] = useState(false);
  const recordedExposures = useRef(new Set<string>());
  const review = useQuery({
    queryKey: ["application-review", applicationId],
    queryFn: ({ signal }) => apiClient.applicationReview(applicationId, signal),
    enabled: Boolean(applicationId),
  });
  const predictionId = review.data?.latest_prediction?.id;

  useEffect(() => {
    if (
      !predictionId
      || !hasPermission("experiment:participate")
      || recordedExposures.current.has(predictionId)
    ) return;
    recordedExposures.current.add(predictionId);
    void apiClient.recordExplanationExposure(predictionId).catch(() => {
      recordedExposures.current.delete(predictionId);
    });
  }, [hasPermission, predictionId]);

  const score = useMutation({
    mutationFn: () => apiClient.createPrediction(applicationId),
    onSuccess: () => void queryClient.invalidateQueries({
      queryKey: ["application-review", applicationId],
    }),
  });
  const feedback = useMutation({
    mutationFn: (id: string) => apiClient.submitFeedback(
      id,
      decision,
      agreement,
      note.trim() || null,
    ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["application-review", applicationId],
      });
      setAmending(false);
      setNote("");
      message.success("Human decision recorded.");
    },
  });

  if (review.isPending) return <PageSkeleton />;
  if (review.isError) {
    if (review.error instanceof ApiError && review.error.status === 403) {
      return <Alert
        type="error"
        showIcon
        message="You do not have access to this application"
        description="Officers can review only applications they created. Portfolio-wide access requires the corresponding permission."
      />;
    }
    return <QueryError error={review.error} onRetry={() => void review.refetch()} />;
  }

  const {
    application,
    latest_prediction: prediction,
    feedback_history: history,
  } = review.data;
  const currentFeedback = review.data.current_feedback ?? history.at(-1) ?? null;
  const chartData = prediction?.explanation.top_features.map((item) => ({
    ...item,
    magnitude: Math.abs(item.contribution),
  })) ?? [];
  const timelineItems = [
    {
      color: "blue",
      children: <>
        Application created {" "}
        <Typography.Text type="secondary">{formatDate(application.created_at)}</Typography.Text>
      </>,
    },
    ...(prediction ? [{
      color: "blue",
      children: <>
        Scored by {prediction.model_version} {" "}
        <Typography.Text type="secondary">{formatDate(prediction.created_at)}</Typography.Text>
      </>,
    }] : []),
    ...history.map((item) => ({
      color: item.decision === "escalate" ? "orange" : "green",
      children: <>
        {item.version && item.version > 1 ? "Decision amended" : "Decision recorded"}: {" "}
        <strong>{titleCase(item.decision)}</strong> {" "}
        <Typography.Text type="secondary">{formatDate(item.created_at)}</Typography.Text>
      </>,
    })),
  ];

  const confirmDecision = () => {
    if ((agreement === false || currentFeedback) && !note.trim()) {
      message.error(
        currentFeedback
          ? "Explain why this decision is being amended."
          : "Explain why the model is being overridden.",
      );
      return;
    }
    modal.confirm({
      title: currentFeedback ? "Confirm amended decision" : "Confirm human decision",
      content: `${titleCase(decision)} will be appended to the permanent decision history.`,
      okText: currentFeedback ? "Amend decision" : "Record decision",
      onOk: () => prediction ? feedback.mutateAsync(prediction.id) : undefined,
    });
  };

  return <>
    <PageIntro
      title={`Application ${application.external_reference ?? application.id.slice(0, 8).toUpperCase()}`}
      purpose="Review the score and context, then record the qualified human decision."
    />
    <DecisionSupportNotice />
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={9}>
        <Card title="Application details">
          <Descriptions
            column={1}
            size="small"
            items={Object.entries(application.features).map(([key, value]) => ({
              key,
              label: titleCase(key.replaceAll("_", " ")),
              children: value ?? "Not provided",
            }))}
          />
        </Card>
      </Col>
      <Col xs={24} xl={15}>
        <Card title="Risk assessment" extra={prediction ? <RiskTag flagged={prediction.risk_flag} /> : null}>
          {prediction ? <>
            <Row gutter={[24, 16]} align="middle">
              <Col xs={24} md={9}>
                <Progress
                  type="dashboard"
                  percent={Math.round(prediction.score * 1000) / 10}
                  strokeColor={prediction.risk_flag ? "#c62828" : "#237804"}
                  format={() => formatPercent(prediction.score)}
                />
              </Col>
              <Col xs={24} md={15}>
                <Typography.Title level={4}>
                  {prediction.risk_flag
                    ? "Above the review threshold - recommend closer review"
                    : "Below the review threshold - continue the full human review"}
                </Typography.Title>
                <Typography.Paragraph>
                  Threshold: {formatPercent(prediction.threshold)} | Model {prediction.model_version}
                </Typography.Paragraph>
              </Col>
            </Row>
            {prediction.explanation.available ? <Card size="small" title="Why the model produced this score">
              <Typography.Paragraph>{prediction.explanation.narrative}</Typography.Paragraph>
              <ul aria-label="Top model contributors">
                {chartData.map((item) => <li key={item.feature}>
                  {item.display_name}: {item.direction === "risk_increasing" ? "increases" : "reduces"} estimated risk
                </li>)}
              </ul>
              <ResponsiveContainer width="100%" height={230}>
                <BarChart data={chartData} layout="vertical" margin={{ left: 24 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="display_name" width={115} />
                  <ChartTooltip />
                  <Bar dataKey="magnitude" isAnimationActive={false}>
                    {chartData.map((item) => <Cell
                      key={item.feature}
                      fill={item.direction === "risk_increasing" ? "#c62828" : "#237804"}
                    />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Card> : <Alert
              type="info"
              showIcon
              message="Explanation not included in this study view"
              description="This score-only assignment receives the score and threshold, but no contributor data or narrative."
            />}
          </> : <EmptyAction
            description="This application has not yet been scored."
            action={hasPermission("prediction:create") ? () => score.mutate() : undefined}
            actionLabel="Request score"
          />}
        </Card>
      </Col>
    </Row>

    {prediction && hasPermission("feedback:create") ? <Card className="section-row" title="Human decision">
      {currentFeedback && !amending ? <Alert
        type="success"
        showIcon
        message={`Decision recorded: ${titleCase(currentFeedback.decision)}`}
        description={<Space direction="vertical">
          <span>{currentFeedback.note || "No note was recorded."}</span>
          <Button onClick={() => {
            setDecision(currentFeedback.decision);
            setAgreement(currentFeedback.agreed_with_model);
            setAmending(true);
          }}>Amend decision</Button>
        </Space>}
      /> : <>
        <Radio.Group
          value={decision}
          onChange={(event) => setDecision(event.target.value)}
          options={["approve", "decline", "escalate"].map((value) => ({
            label: titleCase(value),
            value,
          }))}
        />
        <Form layout="vertical" className="section-row">
          <Form.Item label="Did you agree with the model?">
            <Radio.Group
              value={agreement === null ? "not_recorded" : agreement}
              onChange={(event) => setAgreement(event.target.value === "not_recorded" ? null : event.target.value)}
              options={[
                { label: "Yes", value: true },
                { label: "No - override", value: false },
                { label: "Not recorded", value: "not_recorded" },
              ]}
            />
          </Form.Item>
          <Form.Item
            label="Decision note"
            required={agreement === false || Boolean(currentFeedback)}
            help={agreement === false
              ? "A reason is required when overriding the model."
              : currentFeedback
                ? "A reason is required for every amendment."
                : "Optional supporting context."}
          >
            <Input.TextArea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={2000}
            />
          </Form.Item>
          <Space>
            <Button type="primary" loading={feedback.isPending} onClick={confirmDecision}>
              {currentFeedback ? "Review amendment" : "Review decision"}
            </Button>
            {currentFeedback ? <Button onClick={() => {
              setAmending(false);
              setNote("");
            }}>Cancel</Button> : null}
          </Space>
          {feedback.isError ? <Alert
            className="section-row"
            type="error"
            showIcon
            message="Decision could not be recorded"
            description={feedback.error instanceof ApiError ? feedback.error.detail : "Try again."}
          /> : null}
        </Form>
      </>}
    </Card> : null}

    <Row className="section-row" gutter={[16, 16]}>
      <Col xs={24} xl={15}>
        <Card title="Decision history">
          {history.length ? <Table
            rowKey="id"
            pagination={false}
            dataSource={history}
            columns={[
              { title: "Version", dataIndex: "version", render: (value: number | undefined) => value ?? 1 },
              { title: "Decision", dataIndex: "decision", render: titleCase },
              { title: "Agreement", dataIndex: "agreed_with_model", render: (value: boolean | null) => value == null ? "Not recorded" : value ? "Agreed" : "Overrode" },
              { title: "Recorded", dataIndex: "created_at", render: formatDate },
              { title: "Note", dataIndex: "note", render: (value: string | null) => value || "Not provided" },
            ]}
          /> : <EmptyAction description="No human decision has been recorded." />}
        </Card>
      </Col>
      <Col xs={24} xl={9}>
        <Card title="Application timeline"><Timeline items={timelineItems} /></Card>
      </Col>
    </Row>
  </>;
}
