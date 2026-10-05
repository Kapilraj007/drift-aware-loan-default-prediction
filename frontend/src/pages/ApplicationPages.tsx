import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Col, DatePicker, Descriptions, Form, Input, InputNumber, Modal, Radio, Row, Select, Space, Steps, Table, Tag, Typography, Upload } from "antd";
import type { UploadProps } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useEffect, useMemo, useRef, useState } from "react";
import { useBeforeUnload, useNavigate, useParams } from "react-router-dom";
import { apiClient, ApiError } from "../api/client";
import { DecisionSupportNotice, EmptyAction, PageIntro, PageSkeleton, QueryError, RiskTag } from "../components/Page";
import { useAuth } from "../context/AuthContext";
import { draftFromRecord, toApplicationFeatures, validateApplicationDraft } from "../lib/applicationData";
import { parseApplicationFile } from "../lib/csv";
import { formatDate, formatPercent, titleCase } from "../lib/format";
import type { ApplicationDraft, ApplicationFeatureName, ApplicationFieldDefinition, ApplicationResponse, OfficerDecision } from "../types";
import { applicationFields, emptyApplicationDraft } from "../types";

const sampleApplication: Record<string, unknown> = {
  annual_inc: 75000, dti: 16.5, revol_util: "38%", revol_bal: 28000,
  emp_length: "5 years", home_ownership: "MORTGAGE", loan_amnt: 12000,
  term: "36 months", int_rate: "11.2%", installment: 395, grade: "B",
  sub_grade: "B3", purpose: "debt_consolidation", issue_d: "Jan-2018",
  open_acc: 10, total_acc: 22, delinq_2yrs: 0, inq_last_6mths: 1,
  earliest_cr_line: "Jan-2004",
};

function monthValue(value: string) {
  const iso = /^(\d{4})-(\d{2})/.exec(value);
  if (iso) return dayjs(`${iso[1]}-${iso[2]}-01`);
  const named = /^([A-Z][a-z]{2})-(\d{4})$/.exec(value);
  if (!named) return null;
  const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].indexOf(named[1]);
  return month < 0 ? null : dayjs(`${named[2]}-${String(month + 1).padStart(2, "0")}-01`);
}

function DraftField({ field, value, error, update }: {
  field: ApplicationFieldDefinition;
  value: string;
  error?: string;
  update: (name: ApplicationFeatureName, value: string) => void;
}) {
  const inputId = `application-${field.name}`;
  const options = field.allowed_values ?? field.options;
  const help = error ?? field.help_text ?? field.help ?? field.description;
  let control;
  if (field.kind === "month" || field.type === "month") {
    control = <DatePicker id={inputId} picker="month" className="full-width" value={monthValue(value)} onChange={(_, text) => { const selected = Array.isArray(text) ? text[0] : text; update(field.name, selected ? dayjs(selected).format("MMM-YYYY") : ""); }} />;
  } else if (options?.length) {
    control = <Select id={inputId} allowClear showSearch value={value || undefined} options={options.map((option) => ({ value: String(option), label: titleCase(String(option)) }))} onChange={(next) => update(field.name, next ?? "")} />;
  } else if (field.kind === "number" || field.type === "number") {
    control = <InputNumber id={inputId} className="full-width" stringMode value={value || null} min={field.minimum == null ? undefined : String(field.minimum)} max={field.maximum == null ? undefined : String(field.maximum)} onChange={(next) => update(field.name, next === null ? "" : String(next))} />;
  } else {
    control = <Input id={inputId} value={value} placeholder={field.placeholder} onChange={(event) => update(field.name, event.target.value)} />;
  }
  return <Col xs={24} md={12} xl={8}><Form.Item htmlFor={inputId} label={field.label} required={field.required} validateStatus={error ? "error" : undefined} help={help}>{control}</Form.Item></Col>;
}

export function NewApplicationPage() {
  const navigate = useNavigate();
  const [draft, setDraft] = useState<ApplicationDraft>(emptyApplicationDraft);
  const [reference, setReference] = useState("");
  const [step, setStep] = useState(0);
  const [errors, setErrors] = useState<Partial<Record<ApplicationFeatureName, string>>>({});
  const [importRecord, setImportRecord] = useState<Record<string, unknown> | null>(null);
  const submitted = useRef(false);
  const schema = useQuery({ queryKey: ["application-schema"], queryFn: ({ signal }) => apiClient.applicationSchema(signal) });
  const fields = schema.data?.fields ?? applicationFields;
  const groups = useMemo(() => ["Applicant & finances", "Loan details", "Credit history"], []);
  const dirty = !submitted.current && (reference.trim().length > 0 || Object.values(draft).some(Boolean));

  useBeforeUnload((event) => {
    if (dirty) event.preventDefault();
  });
  useEffect(() => {
    const protectInternalNavigation = (event: MouseEvent) => {
      const anchor = (event.target as HTMLElement).closest("a");
      if (dirty && anchor?.href && new URL(anchor.href).origin === window.location.origin && !window.confirm("Leave this application? Unsaved changes will be lost.")) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    document.addEventListener("click", protectInternalNavigation, true);
    return () => document.removeEventListener("click", protectInternalNavigation, true);
  }, [dirty]);

  const create = useMutation({
    mutationFn: async () => {
      const application = await apiClient.createApplication(reference || null, toApplicationFeatures(draft));
      await apiClient.createPrediction(application.id);
      return application;
    },
    onSuccess: (result) => {
      submitted.current = true;
      navigate(`/applications/${result.id}`);
    },
    onError: (error) => {
      if (!(error instanceof ApiError)) return;
      const fieldErrors: Partial<Record<ApplicationFeatureName, string>> = {};
      for (const item of error.fieldErrors) {
        const name = item.field.replace(/^features\./, "") as ApplicationFeatureName;
        if (fields.some((field) => field.name === name)) {
          fieldErrors[name] = item.message;
        }
      }
      if (Object.keys(fieldErrors).length) {
        setErrors(fieldErrors);
        setStep(3);
      }
    },
  });
  const quality = validateApplicationDraft(draft, fields);
  const update = (name: ApplicationFeatureName, value: string) => {
    setDraft((current) => ({ ...current, [name]: value }));
    setErrors((current) => ({ ...current, [name]: undefined }));
  };
  const upload: UploadProps = {
    accept: ".csv,.json", showUploadList: false,
    beforeUpload: async (file) => {
      try { setImportRecord(await parseApplicationFile(file)); }
      catch (error) { Modal.error({ title: "Import could not be read", content: error instanceof Error ? error.message : "Use a CSV or JSON application file." }); }
      return Upload.LIST_IGNORE;
    },
  };
  const submit = () => {
    setErrors(quality.errors);
    if (!quality.valid) {
      setStep(3);
      return;
    }
    create.mutate();
  };
  const recognized = importRecord ? fields.filter((field) => Object.hasOwn(importRecord, field.name)) : [];
  const ignored = importRecord ? Object.keys(importRecord).filter((key) => !fields.some((field) => field.name === key)) : [];

  if (schema.isPending) return <PageSkeleton />;
  if (schema.isError) return <QueryError error={schema.error} onRetry={() => void schema.refetch()} />;
  return <>
    <PageIntro title="New application" purpose="Enter, validate, review, and score one application through a guided four-step workflow." extra={<Space><Button onClick={() => setDraft(draftFromRecord(sampleApplication))}>Load sample</Button><Upload {...upload}><Button>Import CSV / JSON</Button></Upload></Space>} />
    <DecisionSupportNotice />
    <Card>
      <Steps current={step} items={[...groups, "Review & submit"].map((title) => ({ title }))} onChange={setStep} />
      <Form layout="vertical" className="section-row">
        {step < 3 ? <><Form.Item label="External reference" help="Optional case reference used to find this application later."><Input value={reference} onChange={(event) => setReference(event.target.value)} placeholder="CASE-2026-001" /></Form.Item><Row gutter={[16, 0]}>{fields.filter((field) => field.group === groups[step]).map((field) => <DraftField key={field.name} field={field} value={draft[field.name]} error={errors[field.name]} update={update} />)}</Row></> : <>
          <Alert type={quality.valid ? "success" : "error"} showIcon message={quality.valid ? "Data-quality checks passed" : "Resolve the highlighted data-quality issues"} description={quality.valid ? `${fields.filter((field) => draft[field.name]).length} recognised fields will be submitted.` : Object.values(quality.errors).join(" ")} />
          {quality.warnings.length ? <Alert className="section-row" type="warning" showIcon message="Values to verify" description={quality.warnings.join(" ")} /> : null}
          {groups.map((group) => <Card size="small" className="section-row" title={group} key={group}><Descriptions size="small" column={{ xs: 1, md: 2 }} items={fields.filter((field) => field.group === group).map((field) => ({ key: field.name, label: field.label, children: draft[field.name] || "Not provided" }))} /></Card>)}
        </>}
        <Space className="section-row"><Button disabled={step === 0} onClick={() => setStep((value) => value - 1)}>Back</Button>{step < 3 ? <Button type="primary" onClick={() => setStep((value) => value + 1)}>Continue</Button> : <Button type="primary" loading={create.isPending} onClick={submit}>Create and score application</Button>}</Space>
        {create.isError ? <Alert className="section-row" type="error" showIcon message="Application could not be scored" description={create.error instanceof ApiError ? create.error.detail : "Try again."} /> : null}
      </Form>
    </Card>
    <Modal open={Boolean(importRecord)} title="Preview imported application" okText="Use recognised fields" onCancel={() => setImportRecord(null)} onOk={() => { if (importRecord) setDraft(draftFromRecord(importRecord)); setImportRecord(null); }}>
      <Alert type="info" showIcon message={`${recognized.length} recognised columns`} description={ignored.length ? `Ignored columns: ${ignored.join(", ")}` : "Every supplied column is recognised."} />
      <Table className="section-row" size="small" pagination={{ pageSize: 6 }} rowKey="name" dataSource={recognized} columns={[{ title: "Field", dataIndex: "label" }, { title: "Imported value", render: (_, field) => String(importRecord?.[field.name] ?? "") }]} />
    </Modal>
  </>;
}
const columns: ColumnsType<ApplicationResponse> = [{ title: "Reference", render: (_, row) => row.external_reference || row.id.slice(0, 8).toUpperCase() }, { title: "Created", dataIndex: "created_at", render: formatDate }, { title: "Score", dataIndex: "latest_score", render: (value: number | null) => value == null ? "Not scored" : formatPercent(value) }, { title: "Risk", dataIndex: "risk_flag", render: (value: boolean | null) => value == null ? "Not scored" : <RiskTag flagged={value} /> }, { title: "Status", dataIndex: "status", render: (value: string | undefined) => <Tag>{value ?? "created"}</Tag> }];
export function LegacyApplicationsPage() {
  const navigate = useNavigate(); const [search, setSearch] = useState(""); const [offset, setOffset] = useState(0); const query = useQuery({ queryKey: ["applications", search, offset], queryFn: ({ signal }) => apiClient.applications({ search, offset, limit: 20 }, signal) });
  return <><PageIntro title="Applications" purpose="Find applications you can review and continue an auditable decision." extra={<Button type="primary" onClick={() => navigate("/applications/new")}>New application</Button>} /><Card><Input.Search className="section-row" allowClear placeholder="Reference or application ID" onSearch={(value) => { setSearch(value); setOffset(0); }} />{query.isPending ? <PageSkeleton /> : query.isError ? <QueryError error={query.error} onRetry={() => void query.refetch()} /> : query.data.items.length ? <Table rowKey="id" columns={columns} dataSource={query.data.items} pagination={{ current: offset / 20 + 1, pageSize: 20, total: query.data.total, onChange: (page) => setOffset((page - 1) * 20) }} onRow={(row) => ({ onClick: () => navigate(`/applications/${row.id}`), className: "clickable-row" })} /> : <EmptyAction description="No applications match this view." />}</Card></>;
}
export function LegacyApplicationReviewPage() {
  const { applicationId = "" } = useParams(); const queryClient = useQueryClient(); const { hasPermission } = useAuth(); const [decision, setDecision] = useState<OfficerDecision>("approve"); const [note, setNote] = useState(""); const [agreement, setAgreement] = useState<boolean | null>(null);
  const review = useQuery({ queryKey: ["application-review", applicationId], queryFn: ({ signal }) => apiClient.applicationReview(applicationId, signal), enabled: Boolean(applicationId) }); const score = useMutation({ mutationFn: () => apiClient.createPrediction(applicationId), onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["application-review", applicationId] }) }); const feedback = useMutation({ mutationFn: (id: string) => apiClient.submitFeedback(id, decision, agreement, note || null), onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["application-review", applicationId] }) });
  if (review.isPending) return <PageSkeleton />; if (review.isError) return <QueryError error={review.error} onRetry={() => void review.refetch()} />; const { application, latest_prediction: prediction, feedback_history: history } = review.data;
  return <><PageIntro title={`Application ${application.external_reference ?? application.id.slice(0, 8).toUpperCase()}`} purpose="Review the score and context, then record the qualified human decision." /><DecisionSupportNotice /><Row gutter={[16, 16]}><Col xs={24} xl={10}><Card title="Application details"><Descriptions column={1} size="small" items={Object.entries(application.features).map(([key, value]) => ({ key, label: titleCase(key.replaceAll("_", " ")), children: value ?? "—" }))} /></Card></Col><Col xs={24} xl={14}><Card title="Risk assessment" extra={prediction ? <RiskTag flagged={prediction.risk_flag} /> : null}>{prediction ? <><Typography.Title level={2}>{formatPercent(prediction.score)} <Typography.Text type="secondary">risk score</Typography.Text></Typography.Title><Typography.Paragraph>Threshold: {formatPercent(prediction.threshold)} · Model {prediction.model_version}</Typography.Paragraph>{prediction.explanation.available ? <ul>{prediction.explanation.top_features.map((item) => <li key={item.feature}>{item.display_name}: {item.direction === "risk_increasing" ? "increases" : "reduces"} risk</li>)}</ul> : <Alert type="info" message="Score-only study variant" description="This assignment intentionally does not show model explanations." />}</> : <EmptyAction description="This application has not yet been scored." action={hasPermission("prediction:create") ? () => score.mutate() : undefined} actionLabel="Request score" />}</Card></Col></Row>{prediction && hasPermission("feedback:create") ? <Card className="section-row" title="Record officer decision"><Radio.Group value={decision} onChange={(event) => setDecision(event.target.value)} options={["approve", "decline", "escalate"].map((value) => ({ label: titleCase(value), value }))} /><Form layout="vertical" className="section-row"><Form.Item label="Did you agree with the model?"><Radio.Group value={agreement} onChange={(event) => setAgreement(event.target.value)} options={[{ label: "Yes", value: true }, { label: "No", value: false }, { label: "Not recorded", value: null }]} /></Form.Item><Form.Item label="Decision note"><Input.TextArea value={note} onChange={(event) => setNote(event.target.value)} maxLength={2000} /></Form.Item><Button type="primary" loading={feedback.isPending} onClick={() => feedback.mutate(prediction.id)}>Save human decision</Button></Form></Card> : null}<Card className="section-row" title="Decision history">{history.length ? <Table rowKey="id" pagination={false} dataSource={history} columns={[{ title: "Decision", dataIndex: "decision", render: titleCase }, { title: "Agreement", dataIndex: "agreed_with_model", render: (value: boolean | null) => value == null ? "Not recorded" : value ? "Agreed" : "Overrode" }, { title: "Recorded", dataIndex: "created_at", render: formatDate }, { title: "Note", dataIndex: "note" }]} /> : <EmptyAction description="No human decision has been recorded." />}</Card></>;
}
