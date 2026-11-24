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
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMe } from "../auth/useMe";
import { getDeviceKey, setDeviceKey, clearDeviceKey } from "../lib/deviceKey";
import { startCamera, type CameraHandle } from "../lib/camera";
import {
  ApiError,
  getCurrentPosition,
  newClientPunchId,
  resolveEmployeeByCode,
  submitPunch,
  type EmployeeLookup,
  type PositionResult,
} from "../api/clockIn";
import { strings } from "../lib/strings";
import { colors } from "../theme/colors";

type Phase = "need_key" | "ready" | "submitting" | "success" | "error";

/**
 * How the employee proves who they are.
 *
 * "camera" is the code-plus-photo path: the code is self-declared and nothing
 * verifies it, but policy section 1 forbids retaining the photograph, so the
 * photo is validated then discarded. It is therefore identification without
 * verification.
 *
 * "pin" is the non-biometric alternative section 4 of the privacy policy
 * requires. The PIN is verified server-side, so it is genuine verification --
 * weaker than a biometric template, and not represented as equivalent, but
 * strictly stronger than an unverified code.
 *
 * Both are offered on this screen, side by side. Section 4 requires the
 * alternative to be genuinely available, and an option an employee can only
 * find out about from HR is not.
 */
type AuthMode = "camera" | "pin";

const ACCURACY_WARN_METRES = 50;

type Verdict = {
  time: string;
  siteName: string | null;
  result: string | null;
  reason: string | null;
  accuracy: number | null;
  distance: number | null;
  locationProblem: string | null;
};

const SITE_FAULT_REASONS = new Set([
  "site_radius_not_configured",
  "site_coordinates_missing",
  "site_record_missing",
]);

function verdictLabel(result: string | null, reason: string | null): string {
  switch (result) {
    case "inside":
      return strings.clockIn.verdictInside;
    case "outside":
      return strings.clockIn.verdictOutside;
    case "inconclusive":
      return strings.clockIn.verdictInconclusive;
    default:
      if (reason !== null && SITE_FAULT_REASONS.has(reason)) {
        return strings.clockIn.verdictSiteMissing;
      }
      return strings.clockIn.verdictUnavailable;
  }
}

function verdictColor(result: string | null): string {
  if (result === "inside") return colors.approved;
  if (result === "outside") return colors.problem;
  return colors.pending;
}

function describeLocationProblem(pos: PositionResult | null): string | null {
  if (!pos || pos.ok) return null;
  switch (pos.reason) {
    case "denied":
      return strings.clockIn.locationDenied;
    case "timeout":
      return strings.clockIn.locationTimeout;
    case "unsupported":
      return strings.clockIn.locationUnsupported;
    default:
      return strings.clockIn.locationUnavailable;
  }
}

/**
 * Map a PIN failure to guidance the employee can act on.
 *
 * Every branch names a next step. "Incorrect PIN" alone leaves someone typing
 * the same digits again until they are locked out, and a locked-out employee
 * who does not know HR can unlock them will simply stop clocking in.
 */
function pinErrorMessage(e: unknown): string | null {
  if (!(e instanceof ApiError)) return null;
  switch (e.code) {
    case "pin_not_set":
      return strings.clockIn.pinNotSet;
    case "pin_locked":
      return strings.clockIn.pinLocked;
    case "pin_incorrect":
      return e.message || strings.clockIn.pinIncorrect;
    case "pin_required":
      return strings.clockIn.pinRequired;
    default:
      return null;
  }
}

/**
 * Read a numeric field that may be absent, null, or a decimal string.
 *
 * Number("") and Number(null) are both 0, so a naive Number() would show
 * "accurate to 0 m" when the accuracy is simply unknown.
 */
function num(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function ClockInPage() {
  const me = useMe();
  const [deviceKey, setDeviceKeyState] = useState<string | null>(getDeviceKey());
  const [keyInput, setKeyInput] = useState("");
  const [phase, setPhase] = useState<Phase>(
    deviceKey ? "ready" : "need_key",
  );
  const [employeeCode, setEmployeeCode] = useState("");
  const [employee, setEmployee] = useState<EmployeeLookup | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("camera");
  const [pin, setPin] = useState("");
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [warningMsg, setWarningMsg] = useState<string | null>(null);
  const [position, setPosition] = useState<PositionResult | null>(null);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
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
    setPin("");
    setAuthMode("camera");
    stopCamera();
    setSuccessMsg(null);
    setWarningMsg(null);
    setErrorMsg(null);
    setPosition(null);
    setVerdict(null);
  };

  const switchMode = (next: string) => {
    const mode = next as AuthMode;
    setAuthMode(mode);
    setErrorMsg(null);
    // Switching away from the camera must release it: holding a camera open
    // for a mode the employee is not using looks like surveillance.
    if (mode === "pin") stopCamera();
  };

  const lookup = async () => {
    setErrorMsg(null);
    setVerdict(null);
    try {
      const found = await resolveEmployeeByCode(employeeCode.trim());
      if (!found) {
        setErrorMsg(strings.clockIn.noMatch);
        setEmployee(null);
        return;
      }
      setEmployee(found);
      setPosition(null);
      void getCurrentPosition().then(setPosition);
    } catch (e) {
      setErrorMsg((e as Error).message || strings.clockIn.lookupFailed);
      setEmployee(null);
    }
  };

  const clockIn = async () => {
    if (!employee) return;

    if (authMode === "camera" && (!cameraOn || !cameraRef.current)) {
      setErrorMsg(strings.clockIn.needPhoto);
      return;
    }
    if (authMode === "pin" && pin.trim().length === 0) {
      setErrorMsg(strings.clockIn.pinRequired);
      return;
    }

    setPhase("submitting");
    setErrorMsg(null);
    setSuccessMsg(null);
    setWarningMsg(null);
    setVerdict(null);
    try {
      const photo =
        authMode === "camera" && cameraRef.current
          ? cameraRef.current.captureJpegBase64(0.7)
          : null;
      const now = new Date().toISOString();

      let pos = position;
      if (!pos) {
        pos = await getCurrentPosition();
        setPosition(pos);
      }

      const out = await submitPunch(
        {
          client_punch_id: newClientPunchId(),
          employee_id: employee.id,
          device_time: now,
          device_now_at_send: now,
          method: authMode === "pin" ? "pin" : "code",
          ...(photo ? { photo_base64: photo } : {}),
          ...(authMode === "pin" ? { pin: pin.trim() } : {}),
          ...(pos.ok
            ? {
                latitude: pos.latitude,
                longitude: pos.longitude,
                gps_accuracy_m: pos.gps_accuracy_m,
              }
            : {}),
        },
        deviceKey,
      );

      const t = new Date(out.effective_time).toLocaleTimeString();

      const fix = out.location ?? null;
      const accuracy =
        num(fix?.gps_accuracy_m) ?? (pos.ok ? pos.gps_accuracy_m : null);
      const distance = num(fix?.distance_m);

      setVerdict({
        time: t,
        siteName: out.site_name ?? null,
        result: out.geofence_result ?? null,
        reason: out.geofence_reason ?? null,
        accuracy,
        distance,
        locationProblem: describeLocationProblem(pos),
      });

      if (out.warnings && out.warnings.length > 0) {
        setWarningMsg(strings.clockIn.recomputeWarning);
      } else {
        setSuccessMsg(strings.clockIn.success.replace("{time}", t));
      }
      setPhase("success");
      setEmployee(null);
      setEmployeeCode("");
      setPin("");
      stopCamera();
    } catch (e) {
      // Named intermediate rather than nested ??/|| -- the two operators
      // cannot be mixed without parentheses, and the precedence is not
      // obvious to a reader either.
      const pinMsg = pinErrorMessage(e);
      const fallback = (e as Error).message || strings.clockIn.submitFailed;
      setErrorMsg(pinMsg ?? fallback);
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

  const accuracyHint =
    position?.ok && position.gps_accuracy_m > ACCURACY_WARN_METRES
      ? strings.clockIn.accuracyWarning(Math.round(position.gps_accuracy_m))
      : null;

  const locating = position === null && employee !== null;

  const verdictParts: string[] = [];
  if (verdict) {
    verdictParts.push(verdict.siteName ?? strings.clockIn.unknownSite);
    if (verdict.accuracy != null) {
      verdictParts.push(strings.clockIn.accurateTo(Math.round(verdict.accuracy)));
    }
    if (verdict.result === "outside" && verdict.distance != null) {
      verdictParts.push(strings.clockIn.distanceFromSite(Math.round(verdict.distance)));
    }
    verdictParts.push(verdictLabel(verdict.result, verdict.reason));
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
        <Alert color={colors.pending} data-testid="clockin-identity-notice">
          {strings.clockIn.identityNotice}
        </Alert>
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
        {verdict && (
          <Alert
            color={verdictColor(verdict.result)}
            data-testid="clockin-verdict"
          >
            {verdictParts.join(" · ")}
            {verdict.locationProblem && (
              <Text size="sm" mt={4}>
                {verdict.locationProblem}
              </Text>
            )}
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
                setPosition(null);
                setVerdict(null);
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
            {locating && (
              <Text size="sm" c="dimmed" data-testid="clockin-locating">
                {strings.clockIn.locating}
              </Text>
            )}
            {accuracyHint && (
              <Alert color={colors.pending} data-testid="clockin-accuracy-warning">
                {accuracyHint}
              </Alert>
            )}
          </Stack>
        </Card>

        {employee && (
          <Card withBorder>
            <Stack>
              <SegmentedControl
                fullWidth
                value={authMode}
                onChange={switchMode}
                data={[
                  { label: strings.clockIn.useCamera, value: "camera" },
                  { label: strings.clockIn.usePin, value: "pin" },
                ]}
                data-testid="clockin-auth-mode"
              />

              {authMode === "camera" ? (
                <>
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
                </>
              ) : (
                <>
                  <PasswordInput
                    label={strings.clockIn.pinLabel}
                    placeholder={strings.clockIn.pinPlaceholder}
                    value={pin}
                    onChange={(e) => setPin(e.currentTarget.value)}
                    maxLength={6}
                    inputMode="numeric"
                    data-testid="clockin-pin"
                  />
                  <Text size="xs" c="dimmed">
                    {strings.clockIn.pinHint}
                  </Text>
                </>
              )}

              <Button
                onClick={clockIn}
                disabled={
                  !employee ||
                  phase === "submitting" ||
                  (authMode === "camera" && !cameraOn) ||
                  (authMode === "pin" && pin.trim().length === 0)
                }
                data-testid="clockin-submit"
              >
                {phase === "submitting"
                  ? strings.clockIn.submitting
                  : strings.clockIn.clockInNow}
              </Button>
            </Stack>
          </Card>
        )}
      </Stack>
    </Container>
  );
}