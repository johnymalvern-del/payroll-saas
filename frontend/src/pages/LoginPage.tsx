import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Container,
  PasswordInput,
  Stack,
  TextInput,
  Title,
} from "@mantine/core";
import { useAuth } from "../auth/AuthContext";
import { strings } from "../lib/strings";
import { getTenantSlug, setTenantSlug } from "../api/tenant";

export function LoginPage() {
  const { status, loginError, busy, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation() as { state?: { from?: string } };
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [tenant, setTenant] = useState(getTenantSlug() ?? "");
  const isDev = import.meta.env.DEV;

  if (status === "authenticated") {
    return <Navigate to={location.state?.from ?? "/"} replace />;
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isDev) setTenantSlug(tenant.trim() || null);
    const ok = await login(identifier.trim(), password);
    if (ok) navigate(location.state?.from ?? "/", { replace: true });
  };

  return (
    <Container size="xs" py="xl">
      <form onSubmit={onSubmit}>
        <Stack>
          <Title order={2}>{strings.login.title}</Title>
          {loginError ? <Alert color="red">{loginError}</Alert> : null}
          {isDev ? (
            <TextInput
              label={strings.login.tenantLabel}
              value={tenant}
              onChange={(e) => setTenant(e.currentTarget.value)}
              autoComplete="off"
            />
          ) : null}
          <TextInput
            label={strings.login.identifierLabel}
            value={identifier}
            onChange={(e) => setIdentifier(e.currentTarget.value)}
            required
            autoComplete="username"
          />
          <PasswordInput
            label={strings.login.passwordLabel}
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            required
            autoComplete="current-password"
          />
          <Button type="submit" loading={busy}>
            {strings.login.submit}
          </Button>
        </Stack>
      </form>
    </Container>
  );
}
