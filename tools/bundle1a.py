"""Bundle 1A: write 4 lib/api files + 2 pages for clock-in and devices."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

FILES = {
    "src/lib/deviceKey.ts": '''const STORAGE_KEY = "payroll.device_key";

export function getDeviceKey(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setDeviceKey(key: string): boolean {
  try {
    localStorage.setItem(STORAGE_KEY, key);
    return true;
  } catch {
    return false;
  }
}

export function clearDeviceKey(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignored — screen must still work without storage
  }
}
''',

    "src/lib/camera.ts": '''export type CameraHandle = {
  stop: () => void;
  captureJpegBase64: (quality?: number) => string;
};

export async function startCamera(
  video: HTMLVideoElement,
): Promise<CameraHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "user", width: 640, height: 480 },
    audio: false,
  });
  video.srcObject = stream;
  await video.play();
  const canvas = document.createElement("canvas");
  return {
    stop() {
      stream.getTracks().forEach((t) => t.stop());
      video.srcObject = null;
    },
    captureJpegBase64(quality = 0.7) {
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 480;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("canvas_unsupported");
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL("image/jpeg", quality);
      const idx = dataUrl.indexOf(",");
      return idx >= 0 ? dataUrl.slice(idx + 1) : dataUrl;
    },
  };
}
''',

    "src/api/devices.ts": '''import { getAccessToken } from "./client";
import { getTenantSlug } from "./tenant";

const BASE = "/api/v1";

export type DeviceOut = {
  id: string;
  site_id: string;
  name: string;
  device_type: string;
  status: string;
  last_seen_at: string | null;
  last_sync_at: string | null;
  pending_punch_count: number;
  allows_code_only: boolean;
  require_photo_for_code: boolean;
  software_version: string | null;
  row_version: number;
};

export type DeviceCreateIn = {
  site_id: string;
  name: string;
  device_type: string;
  allows_code_only?: boolean;
  require_photo_for_code?: boolean;
  software_version?: string | null;
};

export type DeviceCreateOut = DeviceOut & { api_key: string };
export type DeviceRotateKeyOut = { id: string; api_key: string };
export type DeviceListOut = {
  items: DeviceOut[];
  next_cursor?: string | null;
  total?: number | null;
};

function authHeaders(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const slug = getTenantSlug();
  if (slug) h["X-Tenant-Slug"] = slug;
  const tok = getAccessToken();
  if (tok) h["Authorization"] = `Bearer ${tok}`;
  return h;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    credentials: "include",
    headers: authHeaders(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg =
      (err as { error?: { message?: string } })?.error?.message ??
      `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export const devicesApi = {
  list: () => request<DeviceListOut>("GET", "/devices"),
  create: (body: DeviceCreateIn) =>
    request<DeviceCreateOut>("POST", "/devices", body),
  rotateKey: (id: string) =>
    request<DeviceRotateKeyOut>("POST", `/devices/${id}/rotate-key`),
};
''',

    "src/api/clockIn.ts": '''import { getAccessToken } from "./client";
import { getTenantSlug } from "./tenant";

const BASE = "/api/v1";

export type EmployeeLookup = {
  id: string;
  employee_code: string;
  first_name: string;
  last_name: string;
};

export type PunchIn = {
  client_punch_id: string;
  employee_id: string;
  device_time: string;
  device_now_at_send?: string | null;
  method: string;
  photo_base64?: string | null;
  match_score?: number | string | null;
  liveness_passed?: boolean | null;
};

export type PunchOut = {
  id: string;
  effective_time: string;
  status: string;
  flags: string[];
};

function baseHeaders(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const slug = getTenantSlug();
  if (slug) h["X-Tenant-Slug"] = slug;
  const tok = getAccessToken();
  if (tok) h["Authorization"] = `Bearer ${tok}`;
  return h;
}

export async function resolveEmployeeByCode(
  code: string,
): Promise<EmployeeLookup | null> {
  const url =
    `${BASE}/employees?employee_code=${encodeURIComponent(code)}&limit=2`;
  const res = await fetch(url, { credentials: "include", headers: baseHeaders() });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg =
      (err as { error?: { message?: string } })?.error?.message ??
      `HTTP ${res.status}`;
    throw new Error(msg);
  }
  const body = (await res.json()) as { items?: EmployeeLookup[] };
  const items = body.items ?? [];
  if (items.length === 0) return null;
  if (items.length > 1) {
    throw new Error("employee_code_matches_more_than_one_employee");
  }
  return items[0];
}

export async function submitPunch(
  payload: PunchIn,
  deviceKey: string | null,
): Promise<PunchOut> {
  const h = baseHeaders();
  if (deviceKey) h["X-Device-Key"] = deviceKey;
  const res = await fetch(`${BASE}/punches`, {
    method: "POST",
    credentials: "include",
    headers: h,
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg =
      (err as { error?: { message?: string } })?.error?.message ??
      `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return (await res.json()) as PunchOut;
}

export function newClientPunchId(): string {
  const g = globalThis as { crypto?: Crypto };
  if (g.crypto?.randomUUID) return g.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (g.crypto?.getRandomValues) {
    g.crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
''',

    "src/pages/ClockInPage.tsx": '''import { useEffect, useRef, useState } from "react";
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
      setSuccessMsg(strings.clockIn.success.replace("{time}", t));
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
            <Alert color="blue">{strings.clockIn.intro}</Alert>
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
          <Alert color="red" data-testid="clockin-error">
            {errorMsg}
          </Alert>
        )}
        {successMsg && (
          <Alert color="green" data-testid="clockin-success">
            {successMsg}
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
                color="gray"
                onClick={stopCamera}
                data-testid="clockin-stop-camera"
              >
                {strings.clockIn.stopCamera}
              </Button>
            )}
            {cameraError && <Alert color="orange">{cameraError}</Alert>}
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
''',

    "src/pages/setup/DevicesPage.tsx": '''import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  devicesApi,
  type DeviceCreateOut,
  type DeviceOut,
} from "../../api/devices";
import { strings } from "../../lib/strings";

export function DevicesPage() {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [siteId, setSiteId] = useState("");
  const [name, setName] = useState("");
  const [deviceType, setDeviceType] = useState("browser_webcam");
  const [error, setError] = useState<string | null>(null);
  const [createdKey, setCreatedKey] = useState<DeviceCreateOut | null>(null);
  const [rotated, setRotated] = useState<{ id: string; api_key: string } | null>(
    null,
  );

  const list = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });

  const createM = useMutation({
    mutationFn: devicesApi.create,
    onSuccess: (out) => {
      setCreatedKey(out);
      setCreateOpen(false);
      setName("");
      qc.invalidateQueries({ queryKey: ["devices"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const rotateM = useMutation({
    mutationFn: (id: string) => devicesApi.rotateKey(id),
    onSuccess: (out) => {
      setRotated(out);
      qc.invalidateQueries({ queryKey: ["devices"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{strings.devices.title}</Title>
        <Button
          onClick={() => {
            setError(null);
            setCreateOpen(true);
          }}
          data-testid="devices-add"
        >
          {strings.devices.add}
        </Button>
      </Group>
      {error && (
        <Alert color="red" data-testid="devices-error">
          {error}
        </Alert>
      )}
      {createdKey && (
        <Alert
          color="green"
          data-testid="devices-created-key"
          title={strings.devices.keyOnce}
        >
          <Text fw={700} style={{ fontFamily: "monospace" }}>
            {createdKey.api_key}
          </Text>
          <Text size="xs">{strings.devices.keyCopyNow}</Text>
        </Alert>
      )}
      {rotated && (
        <Alert
          color="blue"
          data-testid="devices-rotated-key"
          title={strings.devices.keyRotated}
        >
          <Text fw={700} style={{ fontFamily: "monospace" }}>
            {rotated.api_key}
          </Text>
        </Alert>
      )}
      {list.isLoading ? (
        <Loader />
      ) : list.isError ? (
        <Alert color="red">{strings.devices.loadFailed}</Alert>
      ) : (
        <Table data-testid="devices-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{strings.devices.colName}</Table.Th>
              <Table.Th>{strings.devices.colType}</Table.Th>
              <Table.Th>{strings.devices.colStatus}</Table.Th>
              <Table.Th>{strings.devices.colLastSeen}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(list.data?.items ?? []).map((d: DeviceOut) => (
              <Table.Tr key={d.id}>
                <Table.Td>{d.name}</Table.Td>
                <Table.Td>{d.device_type}</Table.Td>
                <Table.Td>
                  <Badge>{d.status}</Badge>
                </Table.Td>
                <Table.Td>{d.last_seen_at ?? strings.devices.never}</Table.Td>
                <Table.Td>
                  <Button
                    size="xs"
                    variant="light"
                    onClick={() => rotateM.mutate(d.id)}
                  >
                    {strings.devices.rotate}
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Modal
        opened={createOpen}
        onClose={() => setCreateOpen(false)}
        title={strings.devices.addTitle}
      >
        <Stack>
          <TextInput
            label={strings.devices.siteIdLabel}
            value={siteId}
            onChange={(e) => setSiteId(e.currentTarget.value)}
            data-testid="devices-site-id"
          />
          <TextInput
            label={strings.devices.nameLabel}
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            data-testid="devices-name"
          />
          <Select
            label={strings.devices.typeLabel}
            value={deviceType}
            onChange={(v) => setDeviceType(v ?? "browser_webcam")}
            data={["browser_webcam", "kiosk", "mobile"]}
            data-testid="devices-type"
          />
          <Button
            onClick={() => {
              setError(null);
              createM.mutate({
                site_id: siteId,
                name,
                device_type: deviceType,
              });
            }}
            loading={createM.isPending}
            data-testid="devices-create"
          >
            {strings.devices.create}
          </Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
''',
}

for rel, content in FILES.items():
    p = FRONTEND / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"wrote {rel} ({len(content)} bytes)")