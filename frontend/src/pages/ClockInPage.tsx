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
 * Accuracy above which we warn the employee before they commit.
 *
 * This is a client-side hint only -- the authoritative decision is the
 * server-side geofence verdict, which compares the fix against the site's
 * radius. The number is chosen because an urban fix is typically 5-30 m
 * and mobile-network fallback is 1-3 km: 50 m is roughly where a fix
 * stops being good enough to judge a small office fence.
 */
const ACCURACY_WARN_METRES = 50;

type Verdict = {
  time: string;
  siteName: string | null;
  result: string | null;
  reason: string | null;
  accuracy: number | null;
  distance: number | null;
  /** Why no location was sent, when the fix failed. Null when we had one. */
  locationProblem: string | null;
};

/**
 * Reasons where the *site* is at fault, not the employee's device.
 *
 * The server returns "unavailable" for several distinct reasons. Only some of
 * them mean no location was recorded; the ones below mean a location arrived
 * perfectly well and the site record cannot be compared against it. Telling an
 * employee "No location recorded" in those cases sends them to report a phone
 * that is working correctly.
 */
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
    stopCamera();
    setSuccessMsg(null);
    setWarningMsg(null);
    setErrorMsg(null);
    setPosition(null);
    setVerdict(null);
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
      // Ask for the fix as soon as we know who is clocking, so the accuracy
      // hint can appear before they commit. A refusal here is not an error:
      // the punch still goes through, it simply carries no location.
      setPosition(null);
      void getCurrentPosition().then(setPosition);
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
    setVerdict(null);
    try {
      const photo = cameraRef.current.captureJpegBase64(0.7);
      const now = new Date().toISOString();

      // Reuse the fix taken at lookup time; fetch one now if it was never
      // requested. Never block the punch on it -- an employee who cannot get
      // a location must still be able to clock in, with the day routed to HR.
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
          method: "code",
          photo_base64: photo,
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
      const accuracy =
        out.gps_accuracy_m != null ? Number(out.gps_accuracy_m) : pos.ok ? pos.gps_accuracy_m : null;
      const distance = out.distance_m != null ? Number(out.distance_m) : null;

      setVerdict({
        time: t,
        siteName: out.site_name ?? null,
        result: out.geofence_result ?? null,
        reason: out.geofence_reason ?? null,
        accuracy: Number.isFinite(accuracy as number) ? accuracy : null,
        distance: Number.isFinite(distance as number) ? distance : null,
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