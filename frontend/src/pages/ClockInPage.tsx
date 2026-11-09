import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Center,
  Container,
  Group,
  Loader,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMe } from "../auth/useMe";
import { getDeviceKey, setDeviceKey, clearDeviceKey } from "../lib/deviceKey";
import { startCamera, type CameraHandle } from "../lib/camera";
import {
  newClientPunchId,
  resolveEmployeeByCode,
  submitPunch,
  type EmployeeLookup,
} from "../api/clockIn";
import { strings } from "../lib/strings";
import { colors } from "../theme/colors";

type Phase = "need_key" | "ready" | "submitting" | "success" | "error";

export function ClockInPage() {
  const me = useMe();
  const [deviceKey, setDeviceKeyState] = useState<string | null>(getDeviceKey());
  const [keyInput, setKeyInput] = useState("");
  const [phase, setPhase] = useState<Phase>(
    deviceKey ? "ready" : "need_key",
  );
  const [employeeCode, setEmployeeCode] = useState("");
  const [employee, setEmployee] = useState<EmployeeLookup | null>(null);
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [warningMsg, setWarningMsg] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const cameraRef = useRef<CameraHandle | null>(null);

  useEffect(() => {
    return () => {
      cameraRef.current?.stop();
    };
  }, []);

  const beginCamera = async () => {
    setCameraError(null);
    if (!videoRef.current) return;
    try {
      cameraRef.current = await startCamera(videoRef.current);
      setCameraOn(true);
    } catch {
      setCameraError(strings.clockIn.cameraDenied);
      setCameraOn(false);
    }
  };

  const stopCamera = () => {
    cameraRef.current?.stop();
    cameraRef.current = null;
    setCameraOn(false);
  };

  const saveKey = () => {
    const k = keyInput.trim();
    if (!k) return;
    setDeviceKey(k);
    setDeviceKeyState(k);
    setKeyInput("");
    setPhase("ready");
  };

  const resetDevice = () => {
    clearDeviceKey();
    setDeviceKeyState(null);
    setPhase("need_key");
    setEmployeeCode("");
    setEmployee(null);
    stopCamera();
    setSuccessMsg(null);
    setWarningMsg(null);
    setErrorMsg(null);
  };

  const lookup = async () => {
    setErrorMsg(null);
    try {
      const found = await resolveEmployeeByCode(employeeCode.trim());
      if (!found) {
        setErrorMsg(strings.clockIn.noMatch);
        setEmployee(null);
        return;
      }
      setEmployee(found);
    } catch (e) {
      setErrorMsg((e as Error).message || strings.clockIn.lookupFailed);
      setEmployee(null);
    }
  };

  const clockIn = async () => {
    if (!employee) return;
    if (!cameraOn || !cameraRef.current) {
      setErrorMsg(strings.clockIn.needPhoto);
      return;
    }
    setPhase("submitting");
    setErrorMsg(null);
    setSuccessMsg(null);
    setWarningMsg(null);
    try {
      const photo = cameraRef.current.captureJpegBase64(0.7);
      const now = new Date().toISOString();
      const out = await submitPunch(
        {
          client_punch_id: newClientPunchId(),
          employee_id: employee.id,
          device_time: now,
          device_now_at_send: now,
          method: "code",
          photo_base64: photo,
        },
        deviceKey,
      );
      const t = new Date(out.effective_time).toLocaleTimeString();
      if (out.warnings && out.warnings.length > 0) {
        setWarningMsg(strings.clockIn.recomputeWarning);
      } else {
        setSuccessMsg(strings.clockIn.success.replace("{time}", t));
      }
      setPhase("success");
      setEmployee(null);
      setEmployeeCode("");
      stopCamera();
    } catch (e) {
      setErrorMsg((e as Error).message || strings.clockIn.submitFailed);
      setPhase("error");
    }
  };

  if (me.isLoading) {
    return (
      <Center h="50vh">
        <Loader />
      </Center>
    );
  }

  if (phase === "need_key") {
    return (
      <Container size="xs" py="xl">
        <Card withBorder>
          <Stack>
            <Title order={3}>{strings.clockIn.title}</Title>
            <Alert color={colors.info}>{strings.clockIn.intro}</Alert>
            <PasswordInput
              label={strings.clockIn.deviceKeyLabel}
              value={keyInput}
              onChange={(e) => setKeyInput(e.currentTarget.value)}
              placeholder={strings.clockIn.deviceKeyPlaceholder}
              data-testid="clockin-device-key"
            />
            <Button onClick={saveKey} data-testid="clockin-save-key">
              {strings.clockIn.saveKey}
            </Button>
          </Stack>
        </Card>
      </Container>
    );
  }

  return (
    <Container size="sm" py="xl">
      <Stack>
        <Group justify="space-between">
          <Title order={2}>{strings.clockIn.title}</Title>
          <Button
            variant="subtle"
            size="xs"
            onClick={resetDevice}
            data-testid="clockin-reset-device"
          >
            {strings.clockIn.resetDevice}
          </Button>
        </Group>
        {errorMsg && (
          <Alert color={colors.problem} data-testid="clockin-error">
            {errorMsg}
          </Alert>
        )}
        {successMsg && (
          <Alert color={colors.approved} data-testid="clockin-success">
            {successMsg}
          </Alert>
        )}
        {warningMsg && (
          <Alert
            color={colors.pending}
            data-testid="clockin-recompute-warning"
          >
            {warningMsg}
          </Alert>
        )}
        <Card withBorder>
          <Stack>
            <TextInput
              label={strings.clockIn.codeLabel}
              value={employeeCode}
              onChange={(e) => {
                setEmployeeCode(e.currentTarget.value);
                setEmployee(null);
              }}
              data-testid="clockin-code"
            />
            <Button
              onClick={lookup}
              disabled={!employeeCode.trim()}
              data-testid="clockin-lookup"
            >
              {strings.clockIn.findEmployee}
            </Button>
            {employee && (
              <Text data-testid="clockin-emp">
                {employee.first_name} {employee.last_name} (
                {employee.employee_code})
              </Text>
            )}
          </Stack>
        </Card>
        <Card withBorder>
          <Stack>
            <video
              ref={videoRef}
              style={{ width: "100%", maxWidth: 320, background: "#000" }}
              muted
              playsInline
              data-testid="clockin-video"
            />
            {!cameraOn ? (
              <Button onClick={beginCamera} data-testid="clockin-start-camera">
                {strings.clockIn.startCamera}
              </Button>
            ) : (
              <Button
                color={colors.inactive}
                onClick={stopCamera}
                data-testid="clockin-stop-camera"
              >
                {strings.clockIn.stopCamera}
              </Button>
            )}
            {cameraError && <Alert color={colors.pending}>{cameraError}</Alert>}
            <Button
              onClick={clockIn}
              disabled={!employee || !cameraOn || phase === "submitting"}
              data-testid="clockin-submit"
            >
              {phase === "submitting"
                ? strings.clockIn.submitting
                : strings.clockIn.clockInNow}
            </Button>
          </Stack>
        </Card>
      </Stack>
    </Container>
  );
}
