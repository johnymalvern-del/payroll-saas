import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Center,
  Container,
  Group,
  Loader,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMe } from "../auth/useMe";
import { startCamera, type CameraHandle } from "../lib/camera";
import {
  TEMPLATE_VERSION,
  VENDOR,
  captureEmbedding,
  embeddingToBase64,
} from "../lib/faceEmbedding";
import { colors } from "../theme/colors";

const BASE = "/api/v1";

type Phase = "idle" | "camera" | "submitting" | "done";

/**
 * HR-facing enrolment screen.
 *
 * Every refusal the server can return is surfaced with its own message, because
 * they have different fixes: an unsigned approval is a legal task, a disabled
 * deployment is an operator task, and an absent SDK is a procurement task.
 * "Enrolment failed" would send an HR user to none of those.
 */
const REFUSALS: Record<string, string> = {
  biometric_enrolment_disabled:
    "Biometric enrolment is switched off for this deployment. An operator must enable it after the approval record is signed.",
  biometric_not_approved:
    "No signed biometric approval is on record for this company. Enrolment cannot begin until it is.",
  biometric_approval_tampered:
    "The approval document no longer matches the approval on record. Enrolment is blocked until this is investigated.",
  biometric_approval_expired:
    "The biometric approval has expired and must be renewed.",
  biometric_approval_scope:
    "This employee or site is not covered by the biometric approval.",
  biometric_consent_missing:
    "This employee has not consented to biometric processing. Record consent first. They can use a PIN instead.",
  biometric_not_configured:
    "No face-matching provider is configured on this server. Enrolment is unavailable.",
  biometric_encryption_failed:
    "The template could not be encrypted, so nothing was stored. This is a server configuration problem.",
  biometric_vendor_mismatch:
    "The template format does not match the configured provider.",
  biometric_template_version_mismatch:
    "The template was produced by a different model version than the server expects.",
  biometric_template_invalid:
    "The captured embedding was not usable. Try again with better lighting.",
};

function refusalText(code: string, fallback: string): string {
  return REFUSALS[code] ?? fallback;
}

export function BiometricEnrolPage() {
  const me = useMe();
  const [employeeId, setEmployeeId] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const cameraRef = useRef<CameraHandle | null>(null);

  useEffect(() => {
    return () => {
      cameraRef.current?.stop();
    };
  }, []);

  const begin = async () => {
    setErrorMsg(null);
    setMessage(null);
    setHint(null);
    if (!employeeId.trim()) {
      setErrorMsg("Enter the employee id first.");
      return;
    }
    try {
      if (!videoRef.current) return;
      cameraRef.current = await startCamera(videoRef.current);
      setPhase("camera");
      setHint("Position one face in the frame, then capture.");
    } catch {
      setErrorMsg("The camera could not be started.");
      setPhase("idle");
    }
  };

  const captureAndEnrol = async () => {
    if (!videoRef.current || !cameraRef.current) return;
    setPhase("submitting");
    setErrorMsg(null);
    setHint("Detecting face…");

    const captured = await captureEmbedding(videoRef.current);
    if (!captured.ok) {
      setHint(null);
      setErrorMsg(
        captured.reason === "no_face"
          ? "No face detected. Move closer to the camera and try again."
          : captured.reason === "multiple_faces"
            ? "More than one face in the frame. Only the employee should be visible."
            : "The face model failed to load. Check that /public/models exists.",
      );
      setPhase("camera");
      return;
    }

    setHint("Sending…");
    try {
      const res = await fetch(
        `${BASE}/employees/${encodeURIComponent(employeeId.trim())}/biometric-enrolment`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            biometric_type: "face",
            template_base64: embeddingToBase64(captured.descriptor),
            vendor: VENDOR,
            template_version: TEMPLATE_VERSION,
          }),
        },
      );

      const body = (await res.json().catch(() => ({}))) as {
        error?: { code?: string; message?: string };
      };

      if (!res.ok) {
        const code = body?.error?.code ?? "unknown";
        setErrorMsg(
          refusalText(code, body?.error?.message ?? `HTTP ${res.status}`),
        );
        setPhase("camera");
        setHint(null);
        return;
      }

      cameraRef.current.stop();
      cameraRef.current = null;
      setPhase("done");
      setMessage("Enrolled. The template is stored encrypted on the server.");
      setHint(null);
    } catch {
      setErrorMsg("The request could not be sent. Check the connection.");
      setPhase("camera");
      setHint(null);
    }
  };

  if (me.isLoading) {
    return (
      <Center h="50vh">
        <Loader />
      </Center>
    );
  }

  return (
    <Container size="sm" py="xl">
      <Stack>
        <Title order={2}>Biometric enrolment</Title>
        <Alert color={colors.pending}>
          The face descriptor is computed on this device. The image never leaves
          it. Liveness is not checked — a photograph will match — so a match is
          evidence for review, not proof of presence.
        </Alert>

        {errorMsg && (
          <Alert color={colors.problem} data-testid="enrol-error">
            {errorMsg}
          </Alert>
        )}
        {message && (
          <Alert color={colors.approved} data-testid="enrol-success">
            {message}
          </Alert>
        )}
        {hint && (
          <Text size="sm" c="dimmed" data-testid="enrol-hint">
            {hint}
          </Text>
        )}

        <Card withBorder>
          <Stack>
            <TextInput
              label="Employee id"
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              value={employeeId}
              onChange={(e) => setEmployeeId(e.currentTarget.value)}
              data-testid="enrol-employee"
            />
            <video
              ref={videoRef}
              style={{ width: "100%", maxWidth: 320, background: "#000" }}
              muted
              playsInline
              data-testid="enrol-video"
            />
            {phase === "idle" && (
              <Button onClick={begin} data-testid="enrol-start">
                Start camera
              </Button>
            )}
            {phase === "camera" && (
              <Group>
                <Button onClick={captureAndEnrol} data-testid="enrol-capture">
                  Capture and enrol
                </Button>
              </Group>
            )}
            {phase === "submitting" && <Loader size="sm" />}
            {phase === "done" && (
              <Button
                variant="light"
                onClick={() => {
                  setPhase("idle");
                  setMessage(null);
                  setEmployeeId("");
                }}
                data-testid="enrol-again"
              >
                Enrol another employee
              </Button>
            )}
          </Stack>
        </Card>
      </Stack>
    </Container>
  );
}