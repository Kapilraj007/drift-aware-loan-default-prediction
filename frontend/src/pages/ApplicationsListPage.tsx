import { useQuery } from "@tanstack/react-query";
import { Button, Card, DatePicker, Input, Select, Space, Table, Tag } from "antd";
import type { Dayjs } from "dayjs";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiClient } from "../api/client";
import { EmptyAction, PageIntro, PageSkeleton, QueryError, RiskTag } from "../components/Page";
import { formatDate, formatPercent, titleCase } from "../lib/format";
import type { ApplicationResponse } from "../types";

export function ApplicationsPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string>();
  const [riskFlag, setRiskFlag] = useState<boolean>();
  const [dates, setDates] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["applications", search, status, riskFlag, dates?.[0]?.valueOf(), dates?.[1]?.valueOf(), offset],
    queryFn: ({ signal }) => apiClient.applications({
      search,
      status,
      riskFlag,
      dateFrom: dates?.[0]?.startOf("day").toISOString(),
      dateTo: dates?.[1]?.endOf("day").toISOString(),
      offset,
      limit: 20,
    }, signal),
  });
  const reset = () => {
    setSearch("");
    setStatus(undefined);
    setRiskFlag(undefined);
    setDates(null);
    setOffset(0);
  };
  return <>
    <PageIntro title="Applications" purpose="Search and filter the applications you are permitted to review, then continue an auditable decision." extra={<Button type="primary" onClick={() => navigate("/applications/new")}>New application</Button>} />
    <Card>
      <Space wrap>
        <Input.Search
          allowClear
          placeholder="Reference or application ID"
          onSearch={(value) => {
            setSearch(value);
            setOffset(0);
          }}
        />
        <Select
          allowClear
          placeholder="Status"
          value={status}
          onChange={(value) => {
            setStatus(value);
            setOffset(0);
          }}
          options={["unscored", "scored", "decided", "escalated"].map((value) => ({ value, label: titleCase(value) }))}
        />
        <Select
          allowClear
          placeholder="Risk flag"
          value={riskFlag}
          onChange={(value) => {
            setRiskFlag(value);
            setOffset(0);
          }}
          options={[
            { value: true, label: "Above threshold" },
            { value: false, label: "Below threshold" },
          ]}
        />
        <DatePicker.RangePicker value={dates} onChange={(value) => {
          setDates(value);
          setOffset(0);
        }} />
        <Button onClick={reset}>Clear filters</Button>
      </Space>
      {query.isPending ? <PageSkeleton /> : query.isError ? <QueryError error={query.error} onRetry={() => void query.refetch()} /> : query.data.items.length ? <Table
        className="section-row"
        rowKey="id"
        dataSource={query.data.items}
        pagination={{
          current: offset / 20 + 1,
          pageSize: 20,
          total: query.data.total,
          onChange: (page) => setOffset((page - 1) * 20),
        }}
        onRow={(row) => ({
          onClick: () => navigate(`/applications/${row.id}`),
          className: "clickable-row",
        })}
        columns={[
          { title: "Reference", render: (_: unknown, row: ApplicationResponse) => row.external_reference || row.id.slice(0, 8).toUpperCase() },
          { title: "Created", dataIndex: "created_at", render: formatDate, sorter: (a, b) => a.created_at.localeCompare(b.created_at) },
          { title: "Score", dataIndex: "latest_score", render: (value: number | null) => value == null ? "Not scored" : formatPercent(value), sorter: (a, b) => (a.latest_score ?? -1) - (b.latest_score ?? -1) },
          { title: "Risk", dataIndex: "risk_flag", render: (value: boolean | null) => value == null ? "Not scored" : <RiskTag flagged={value} /> },
          { title: "Decision", dataIndex: "current_decision", render: (value: string | null) => value ? titleCase(value) : "Pending" },
          { title: "Status", dataIndex: "status", render: (value: string | undefined) => <Tag>{titleCase(value ?? "unscored")}</Tag> },
        ]}
      /> : <EmptyAction description="No applications match these filters." action={reset} actionLabel="Clear filters" />}
    </Card>
  </>;
}
