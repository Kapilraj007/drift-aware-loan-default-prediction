import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";
import { ApiError, apiClient } from "../api/client";
import { EmptyAction, PageIntro, PageSkeleton, QueryError } from "../components/Page";
import { formatDate, titleCase } from "../lib/format";
import type { ManagedUser, UserRole } from "../types";

const roleOptions: Array<{ value: UserRole; label: string }> = [
  { value: "loan_officer", label: "Loan officer" },
  { value: "risk_analyst", label: "Risk analyst" },
  { value: "admin", label: "Administrator" },
];

interface UserFormValues {
  username: string;
  password: string;
  role: UserRole;
  full_name?: string;
  email?: string;
  is_active?: boolean;
}

export function UsersPage() {
  const client = useQueryClient();
  const { modal, message } = AntApp.useApp();
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<ManagedUser | null>(null);
  const [temporaryPassword, setTemporaryPassword] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [createForm] = Form.useForm<UserFormValues>();
  const [editForm] = Form.useForm<UserFormValues>();
  const users = useQuery({
    queryKey: ["users", search, offset],
    queryFn: ({ signal }) => apiClient.users({ search, offset, limit: 20 }, signal),
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["users"] });
  const create = useMutation({
    mutationFn: (values: UserFormValues) => apiClient.createUser({
      username: values.username,
      password: values.password,
      role: values.role,
      full_name: values.full_name,
      email: values.email,
    }),
    onSuccess: async () => {
      setCreateOpen(false);
      createForm.resetFields();
      await refresh();
      message.success("User created.");
    },
  });
  const update = useMutation({
    mutationFn: ({ id, payload }: {
      id: string;
      payload: Partial<{
        full_name: string;
        email: string;
        role: UserRole;
        is_active: boolean;
      }>;
    }) => apiClient.updateUser(id, payload),
    onSuccess: async () => {
      setEditTarget(null);
      editForm.resetFields();
      await refresh();
      message.success("User updated.");
    },
    onError: (error) => message.error(error instanceof ApiError ? error.detail : "User update failed."),
  });
  const reset = useMutation({
    mutationFn: (id: string) => apiClient.resetUserPassword(id),
    onSuccess: (result) => {
      setTemporaryPassword(result.temporary_password);
      message.success("Temporary password generated.");
    },
    onError: (error) => message.error(error instanceof ApiError ? error.detail : "Password reset failed."),
  });

  const confirmActiveChange = (user: ManagedUser) => {
    modal.confirm({
      title: user.is_active ? `Deactivate ${user.username}?` : `Reactivate ${user.username}?`,
      content: user.is_active
        ? "Existing tokens will be refused on the account's next request. The audit log will record this action."
        : "The account will be allowed to sign in again.",
      okText: user.is_active ? "Deactivate" : "Reactivate",
      okButtonProps: { danger: user.is_active },
      onOk: () => update.mutateAsync({ id: user.id, payload: { is_active: !user.is_active } }),
    });
  };
  const confirmReset = (user: ManagedUser) => {
    modal.confirm({
      title: `Reset password for ${user.username}?`,
      content: "The old password will stop working immediately. The replacement is shown only once.",
      okText: "Reset password",
      onOk: () => reset.mutateAsync(user.id),
    });
  };
  const openEditor = (user: ManagedUser) => {
    setEditTarget(user);
    editForm.setFieldsValue({
      username: user.username,
      full_name: user.full_name ?? undefined,
      email: user.email ?? undefined,
      role: user.role,
      is_active: user.is_active,
    });
  };

  return <>
    <PageIntro title="Users" purpose="Create and manage active accounts through explicit, auditable administration." extra={<Button type="primary" onClick={() => setCreateOpen(true)}>Create user</Button>} />
    <Card>
      <Input.Search
        allowClear
        className="section-row"
        placeholder="Search username, name, or email"
        onSearch={(value) => {
          setSearch(value);
          setOffset(0);
        }}
      />
      {users.isPending ? <PageSkeleton /> : users.isError ? <QueryError error={users.error} onRetry={() => void users.refetch()} /> : <Table
        rowKey="id"
        dataSource={users.data.items}
        pagination={{
          current: offset / 20 + 1,
          pageSize: 20,
          total: users.data.total,
          onChange: (page) => setOffset((page - 1) * 20),
        }}
        columns={[
          { title: "Username", dataIndex: "username" },
          { title: "Name", dataIndex: "full_name", render: (value: string | null) => value || "Not provided" },
          { title: "Role", dataIndex: "role", render: (value: string) => titleCase(value) },
          { title: "Active", dataIndex: "is_active", render: (value: boolean) => <Tag color={value ? "success" : "default"}>{value ? "Active" : "Inactive"}</Tag> },
          { title: "Last sign in", dataIndex: "last_login_at", render: formatDate },
          { title: "Actions", render: (_, user) => <Space wrap>
            <Button onClick={() => openEditor(user)}>Edit</Button>
            <Button danger={user.is_active} onClick={() => confirmActiveChange(user)}>{user.is_active ? "Deactivate" : "Reactivate"}</Button>
            <Button onClick={() => confirmReset(user)}>Reset password</Button>
          </Space> },
        ]}
      />}
    </Card>

    <Drawer
      width={480}
      open={createOpen}
      title="Create user"
      onClose={() => setCreateOpen(false)}
      extra={<Button type="primary" loading={create.isPending} onClick={() => void createForm.validateFields().then((values) => create.mutate(values))}>Create</Button>}
    >
      <Form form={createForm} layout="vertical" initialValues={{ role: "loan_officer" }}>
        <Form.Item name="username" label="Username" rules={[{ required: true }]}><Input autoComplete="off" /></Form.Item>
        <Form.Item name="full_name" label="Full name"><Input /></Form.Item>
        <Form.Item name="email" label="Email" rules={[{ type: "email" }]}><Input type="email" /></Form.Item>
        <Form.Item name="role" label="Role" rules={[{ required: true }]}><Select options={roleOptions} /></Form.Item>
        <Form.Item name="password" label="Initial password" rules={[{ required: true, min: 10 }]}><Input.Password autoComplete="new-password" /></Form.Item>
      </Form>
      {create.isError ? <Alert type="error" showIcon message="User could not be created" description={create.error instanceof ApiError ? create.error.detail : "Review the form and try again."} /> : null}
    </Drawer>

    <Drawer
      width={480}
      open={Boolean(editTarget)}
      title={editTarget ? `Edit ${editTarget.username}` : "Edit user"}
      onClose={() => setEditTarget(null)}
      extra={<Button type="primary" loading={update.isPending} onClick={() => void editForm.validateFields().then((values) => {
        if (editTarget) {
          update.mutate({
            id: editTarget.id,
            payload: {
              full_name: values.full_name,
              email: values.email,
              role: values.role,
              is_active: values.is_active,
            },
          });
        }
      })}>Save</Button>}
    >
      <Alert type="info" showIcon message="Administrator safeguards are enforced by the API" description="You cannot deactivate yourself or deactivate or demote the last active administrator." />
      <Form form={editForm} layout="vertical" className="section-row">
        <Form.Item name="username" label="Username"><Input disabled /></Form.Item>
        <Form.Item name="full_name" label="Full name"><Input /></Form.Item>
        <Form.Item name="email" label="Email" rules={[{ type: "email" }]}><Input type="email" /></Form.Item>
        <Form.Item name="role" label="Role" rules={[{ required: true }]}><Select options={roleOptions} /></Form.Item>
        <Form.Item name="is_active" label="Account active" valuePropName="checked"><Switch /></Form.Item>
      </Form>
    </Drawer>

    <Modal
      open={Boolean(temporaryPassword)}
      title="Temporary password"
      footer={<Button type="primary" onClick={() => setTemporaryPassword(null)}>I have saved it</Button>}
      closable={false}
    >
      <Alert type="warning" showIcon message="Shown once" description="Copy this value now and send it through an appropriate secure channel. The user must change it." />
      <Typography.Paragraph className="section-row" copyable code>{temporaryPassword}</Typography.Paragraph>
    </Modal>
  </>;
}

export function RolesPage() {
  const roles = useQuery({
    queryKey: ["roles"],
    queryFn: ({ signal }) => apiClient.roles(signal),
  });
  const permissions = useMemo(() => roles.data
    ? [...new Set(roles.data.flatMap((role) => role.permissions))].sort()
    : [], [roles.data]);
  return <>
    <PageIntro title="Roles & permissions" purpose="Review the read-only permission matrix enforced by the seeded RBAC catalog." />
    <Card>
      {roles.isPending ? <PageSkeleton /> : roles.isError ? <QueryError error={roles.error} onRetry={() => void roles.refetch()} /> : permissions.length ? <Table
        rowKey="permission"
        pagination={false}
        scroll={{ x: true }}
        dataSource={permissions.map((permission) => ({ permission }))}
        columns={[
          { title: "Permission", dataIndex: "permission", fixed: "left" },
          ...roles.data.map((role) => ({
            title: titleCase(role.name),
            render: (_: unknown, row: { permission: string }) => role.permissions.includes(row.permission as never)
              ? <Tag color="success">Granted</Tag>
              : <Tag>Not granted</Tag>,
          })),
        ]}
      /> : <EmptyAction description="No roles are available. Run the RBAC seed." />}
    </Card>
  </>;
}

export function AuditPage() {
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [offset, setOffset] = useState(0);
  const audit = useQuery({
    queryKey: ["audit", action, actor, offset],
    queryFn: ({ signal }) => apiClient.auditEvents({ action, actor, offset, limit: 25 }, signal),
  });
  return <>
    <PageIntro title="Audit log" purpose="Search immutable security and workflow events; event history is never edited from the UI." />
    <Card>
      <Space className="section-row" wrap>
        <Input.Search allowClear placeholder="Filter by action" onSearch={(value) => { setAction(value); setOffset(0); }} />
        <Input.Search allowClear placeholder="Filter by actor" onSearch={(value) => { setActor(value); setOffset(0); }} />
      </Space>
      {audit.isPending ? <PageSkeleton /> : audit.isError ? <QueryError error={audit.error} onRetry={() => void audit.refetch()} /> : audit.data.items.length ? <Table
        rowKey="id"
        dataSource={audit.data.items}
        pagination={{
          current: offset / 25 + 1,
          total: audit.data.total,
          pageSize: 25,
          onChange: (page) => setOffset((page - 1) * 25),
        }}
        columns={[
          { title: "Time", dataIndex: "created_at", render: formatDate },
          { title: "Actor", dataIndex: "actor_username", render: (value: string | null, event) => value ?? event.actor_user_id?.slice(0, 8) ?? "System" },
          { title: "Action", dataIndex: "action" },
          { title: "Entity", render: (_, event) => `${event.entity_type ?? "event"}${event.entity_id ? ` | ${event.entity_id.slice(0, 8)}` : ""}` },
          { title: "Metadata", dataIndex: "metadata", render: (value: unknown) => value ? <Typography.Text code>{JSON.stringify(value)}</Typography.Text> : "None" },
        ]}
      /> : <EmptyAction description="No audit events match these filters." />}
    </Card>
  </>;
}
