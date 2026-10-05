import { BankOutlined, LockOutlined, SafetyCertificateOutlined, UserOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Divider, Input, Space, Typography } from "antd";
import { useRef, useState } from "react";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";

const demoAccounts = [
  { label: "Admin", username: "admin", password: "Admin@Demo2026" },
  { label: "Risk analyst", username: "analyst", password: "Analyst@Demo2026" },
  { label: "Officer · explanation", username: "officer.explain", password: "Officer1@Demo2026" },
  { label: "Officer · score only", username: "officer.scoreonly", password: "Officer2@Demo2026" },
] as const;

export function LoginPage() {
  const { signIn, sessionNotice, clearSessionNotice } = useAuth();
  const formRef = useRef<HTMLFormElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fillAccount = (username: string, password: string) => {
    const form = formRef.current;
    const usernameInput = form?.elements.namedItem("username") as HTMLInputElement | null;
    const passwordInput = form?.elements.namedItem("password") as HTMLInputElement | null;
    if (usernameInput) usernameInput.value = username;
    if (passwordInput) passwordInput.value = password;
    usernameInput?.focus();
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const username = String(data.get("username") ?? "").trim();
    const password = String(data.get("password") ?? "");
    if (!username || !password) {
      setError("Enter both your username and password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signIn(username, password);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 423) {
        setError("This account is temporarily locked after repeated attempts. Try again later or contact an administrator.");
      } else {
        setError(reason instanceof ApiError ? reason.detail : "Sign-in failed. Check your credentials and try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login-layout">
      <section className="login-brand-panel" aria-labelledby="product-name">
        <div className="login-brand-content">
          <BankOutlined className="login-mark" aria-hidden />
          <Typography.Title id="product-name">DriftAware</Typography.Title>
          <Typography.Title level={2}>Loan default review, with human judgment at the center.</Typography.Title>
          <Typography.Paragraph>Score applications, understand model signals, record an auditable decision, and monitor whether risk patterns change over time.</Typography.Paragraph>
          <div className="login-principle"><SafetyCertificateOutlined /><span><strong>Decision support only</strong><small>A qualified human always makes the final lending decision.</small></span></div>
        </div>
      </section>
      <section className="login-form-panel" aria-label="Account sign in">
        <Card className="login-card" variant="borderless">
          <Typography.Title level={2}>Sign in</Typography.Title>
          <Typography.Paragraph type="secondary">Use your assigned account to continue to the review workspace.</Typography.Paragraph>
          {sessionNotice ? <Alert closable onClose={() => clearSessionNotice?.()} type="warning" showIcon message={sessionNotice} /> : null}
          {error ? <Alert className="login-error" type="error" showIcon message={error} role="alert" /> : null}
          <form ref={formRef} onSubmit={(event) => void submit(event)}>
            <label htmlFor="username">Username</label>
            <Input id="username" name="username" autoComplete="username" prefix={<UserOutlined />} disabled={busy} />
            <label htmlFor="password">Password</label>
            <Input.Password id="password" name="password" autoComplete="current-password" prefix={<LockOutlined />} disabled={busy} />
            <Button block type="primary" htmlType="submit" loading={busy}>Sign in securely</Button>
          </form>
          {import.meta.env.VITE_SHOW_DEMO_CREDENTIALS === "true" ? (
            <div className="demo-accounts">
              <Divider>Demo accounts · development only</Divider>
              <Space direction="vertical" className="full-width">
                {demoAccounts.map((account) => <Button key={account.username} block onClick={() => fillAccount(account.username, account.password)}>{account.label}</Button>)}
              </Space>
            </div>
          ) : null}
        </Card>
      </section>
    </main>
  );
}
