import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Center,
  Container,
  Loader,
  PasswordInput,
  Stack,
  Title,
} from "@mantine/core";
import { useAuth } from "../auth/AuthContext";
import { useMe } from "../auth/useMe";
import { strings } from "../lib/strings";
import { colors } from "../theme/colors";

export function ForcePasswordChangePage() {
  const { loginError, busy, changePassword } = useAuth();
  const me = useMe();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  if (me.isLoading) {
    return (
      <Center h="50vh">
        <Loader />
      </Center>
    );
  }
  if (me.isError || !me.data) {
    return <Navigate to="/login" replace />;
  }
  if (!me.data.must_change_password) {
    return <Navigate to="/" replace />;
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    if (next.length < 8) {
      setLocalError(strings.changePassword.tooShort);
      return;
    }
    if (next !== confirm) {
      setLocalError(strings.changePassword.mismatch);
      return;
    }
    const ok = await changePassword(current, next);
    if (ok) navigate("/", { replace: true });
  };

  return (
    <Container size="xs" py="xl">
      <form onSubmit={onSubmit}>
        <Stack>
          <Title order={2}>{strings.changePassword.title}</Title>
          <Alert color={colors.info}>{strings.changePassword.intro}</Alert>
          {loginError ? <Alert color={colors.problem}>{loginError}</Alert> : null}
          {localError ? <Alert color={colors.problem}>{localError}</Alert> : null}
          <PasswordInput
            label={strings.changePassword.currentLabel}
            value={current}
            onChange={(e) => setCurrent(e.currentTarget.value)}
            required
            autoComplete="current-password"
          />
          <PasswordInput
            label={strings.changePassword.newLabel}
            value={next}
            onChange={(e) => setNext(e.currentTarget.value)}
            required
            autoComplete="new-password"
          />
          <PasswordInput
            label={strings.changePassword.confirmLabel}
            value={confirm}
            onChange={(e) => setConfirm(e.currentTarget.value)}
            required
            autoComplete="new-password"
          />
          <Button type="submit" loading={busy}>
            {strings.changePassword.submit}
          </Button>
        </Stack>
      </form>
    </Container>
  );
}
