"""Phase 1A — frontend api + page + test + patches."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend" / "src"

# ---------- 1. API client ----------
(FE / "api" / "intelligence.ts").write_text('''import { getAccessToken } from "./client";
import { getTenantSlug } from "./tenant";

const BASE = "/api/v1/intelligence";

export type IntelligenceSettings = {
  id: string;
  default_mode: "traditional" | "assisted" | "autonomous";
  acknowledged_at: string | null;
  acknowledged_by_user_id: string | null;
  row_version: number;
};

export type WorkflowMode = {
  workflow: string;
  company_default: string;
  override_mode: string | null;
  override_active: boolean;
  effective_mode: string;
  row_version: number | null;
  effective_from: string | null;
  autonomous_capability_implemented: boolean;
};

export type ModeChangeLog = {
  id: string;
  changed_by_user_id: string | null;
  changed_at: string;
  workflow: string | null;
  previous_mode: string;
  new_mode: string;
  reason: string;
  effective_from: string;
  audit_id: string | null;
};

function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const slug = getTenantSlug();
  if (slug) h["X-Tenant-Slug"] = slug;
  const tok = getAccessToken();
  if (tok) h["Authorization"] = `Bearer ${tok}`;
  return h;
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    credentials: "include",
    headers: headers(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg =
      (err as { error?: { message?: string } })?.error?.message ??
      `HTTP ${res.status}`;
    const e = new Error(msg) as Error & { code?: string; status?: number };
    e.code = (err as { error?: { code?: string } })?.error?.code;
    e.status = res.status;
    throw e;
  }
  return (await res.json()) as T;
}

export const intelligenceApi = {
  getSettings: () => req<IntelligenceSettings>("GET", "/settings"),
  updateDefaultMode: (body: {
    default_mode: string;
    row_version: number;
    reason: string;
    acknowledged_autonomous?: boolean;
  }) => req<IntelligenceSettings>("PATCH", "/settings/default-mode", body),
  getWorkflowModes: () =>
    req<{ items: WorkflowMode[] }>("GET", "/settings/workflows"),
  updateWorkflowMode: (
    workflow: string,
    body: {
      mode: string;
      is_active: boolean;
      row_version: number | null;
      reason: string;
      acknowledged_autonomous?: boolean;
    },
  ) => req<WorkflowMode>("PATCH", `/settings/workflows/${workflow}`, body),
  getChangeLog: () =>
    req<{ items: ModeChangeLog[] }>("GET", "/settings/change-log?limit=50"),
};
''', encoding="utf-8")
print("wrote api/intelligence.ts")

# ---------- 2. Page ----------
(FE / "pages" / "setup" / "IntelligenceSettingsPage.tsx").write_text('''import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Divider,
  Group,
  Loader,
  Modal,
  Radio,
  SegmentedControl,
  Stack,
  Table,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import { useMe } from "../../auth/useMe";
import {
  intelligenceApi,
  type IntelligenceSettings,
  type ModeChangeLog,
  type WorkflowMode,
} from "../../api/intelligence";
import { PageHeader } from "../../components/layout/PageHeader";
import { EmptyState } from "../../components/layout/EmptyState";
import { TableSkeleton } from "../../components/layout/TableSkeleton";
import { colors } from "../../theme/colors";

const MODE_DESCRIPTIONS: Record<string, { label: string; description: string }> = {
  traditional: {
    label: "Traditional / Manual",
    description:
      "No intelligence recommendations. HR controls every decision, as today.",
  },
  assisted: {
    label: "Assisted",
    description:
      "The system may recommend actions for later workflows, but a human must approve or reject every decision.",
  },
  autonomous: {
    label: "Autonomous",
    description:
      "The system may execute eligible decisions without waiting for HR. Only workflows that are implemented and explicitly authorised can execute; nothing else is affected.",
  },
};

function modeColor(mode: string): string {
  if (mode === "autonomous") return colors.pending;
  if (mode === "assisted") return colors.info;
  return colors.inactive;
}

export function IntelligenceSettingsPage() {
  const me = useMe();
  const qc = useQueryClient();
  const canManage = (me.data?.permissions ?? []).includes("intelligence_manage");

  const [selectedMode, setSelectedMode] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [ackModalOpen, setAckModalOpen] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const settings = useQuery({
    queryKey: ["intelligence", "settings"],
    queryFn: intelligenceApi.getSettings,
    staleTime: 30_000,
  });

  const workflows = useQuery({
    queryKey: ["intelligence", "workflows"],
    queryFn: intelligenceApi.getWorkflowModes,
    staleTime: 30_000,
  });

  const changeLog = useQuery({
    queryKey: ["intelligence", "change-log"],
    queryFn: intelligenceApi.getChangeLog,
    staleTime: 30_000,
  });

  const saveMut = useMutation({
    mutationFn: (payload: {
      default_mode: string;
      row_version: number;
      reason: string;
      acknowledged_autonomous?: boolean;
    }) => intelligenceApi.updateDefaultMode(payload),
    onSuccess: () => {
      setReason("");
      setAck(false);
      setSaveError(null);
      qc.invalidateQueries({ queryKey: ["intelligence"] });
    },
    onError: (e: Error) => {
      setSaveError(
        (e as Error & { code?: string }).code === "autonomous_requires_acknowledgement"
          ? "Autonomous requires explicit acknowledgement."
          : e.message,
      );
    },
  });

  const currentMode = selectedMode ?? settings.data?.default_mode ?? "traditional";
  const modeChanged = currentMode !== settings.data?.default_mode;
  const needsAck = currentMode === "autonomous" && modeChanged && !ack;
  const canSave = canManage && modeChanged && reason.trim().length >= 3 && !needsAck;

  const onSave = () => {
    if (!settings.data) return;
    if (currentMode === "autonomous" && !ack) {
      setAckModalOpen(true);
      return;
    }
    saveMut.mutate({
      default_mode: currentMode,
      row_version: settings.data.row_version,
      reason: reason.trim(),
      acknowledged_autonomous: ack,
    });
  };

  const onAckConfirm = () => {
    setAck(true);
    setAckModalOpen(false);
  };

  if (settings.isLoading) {
    return (
      <Group justify="center" p="xl">
        <Loader />
      </Group>
    );
  }

  if (settings.isError || !settings.data) {
    return (
      <Alert color={colors.problem}>
        Could not load intelligence settings.
        {(settings.error as Error | undefined)?.message?.includes("403")
          ? " You do not have permission to view these settings."
          : ""}
      </Alert>
    );
  }

  return (
    <Stack>
      <PageHeader
        title="Intelligence settings"
        subtitle="Configure how much authority the system has over HR decisions."
      />

      {!canManage && (
        <Alert color={colors.info} data-testid="intel-readonly-notice">
          Read-only view. Only a payroll administrator can change these
          settings.
        </Alert>
      )}

      <Card>
        <Stack gap="sm">
          <Title order={4}>Company-wide default</Title>
          <Text size="sm" c="dimmed">
            This applies to every workflow unless overridden below.
          </Text>
          <SegmentedControl
            value={currentMode}
            onChange={(v) => {
              setSelectedMode(v);
              setSaveError(null);
            }}
            data={[
              { value: "traditional", label: MODE_DESCRIPTIONS.traditional.label },
              { value: "assisted", label: MODE_DESCRIPTIONS.assisted.label },
              { value: "autonomous", label: MODE_DESCRIPTIONS.autonomous.label },
            ]}
            data-testid="intel-company-mode"
            disabled={!canManage}
          />
          <Text size="sm" c="dimmed" data-testid="intel-mode-description">
            {MODE_DESCRIPTIONS[currentMode].description}
          </Text>

          <Textarea
            label="Reason for change (required)"
            value={reason}
            onChange={(e) => setReason(e.currentTarget.value)}
            minRows={2}
            disabled={!canManage}
            data-testid="intel-reason"
            placeholder="Explain why this mode is being set"
          />

          {saveError && (
            <Alert color={colors.problem} data-testid="intel-save-error">
              {saveError}
            </Alert>
          )}

          <Group justify="flex-end">
            <Button
              onClick={onSave}
              disabled={!canSave}
              loading={saveMut.isPending}
              data-testid="intel-save"
            >
              Save
            </Button>
          </Group>
        </Stack>
      </Card>

      <Card>
        <Stack gap="sm">
          <Title order={4}>Workflow overrides</Title>
          <Text size="sm" c="dimmed">
            Each workflow can use a different mode. Inactive overrides fall
            back to the company default.
          </Text>
          {workflows.isLoading ? (
            <TableSkeleton rows={3} cols={4} />
          ) : workflows.isError || !workflows.data ? (
            <Alert color={colors.problem}>Could not load workflows.</Alert>
          ) : (
            <Table data-testid="intel-workflows-table">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Workflow</Table.Th>
                  <Table.Th>Company default</Table.Th>
                  <Table.Th>Override</Table.Th>
                  <Table.Th>Effective mode</Table.Th>
                  <Table.Th>Autonomous ready?</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {workflows.data.items.map((w: WorkflowMode) => (
                  <Table.Tr key={w.workflow}>
                    <Table.Td>{w.workflow.replace(/_/g, " ")}</Table.Td>
                    <Table.Td>
                      <Badge color={modeColor(w.company_default)} variant="light">
                        {w.company_default}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      {w.override_active && w.override_mode
                        ? w.override_mode
                        : "—"}
                    </Table.Td>
                    <Table.Td>
                      <Badge color={modeColor(w.effective_mode)}>
                        {w.effective_mode}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">
                        not yet implemented
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Stack>
      </Card>

      <Card>
        <Stack gap="sm">
          <Title order={4}>Change history</Title>
          {changeLog.isLoading ? (
            <TableSkeleton rows={3} cols={5} />
          ) : changeLog.isError || !changeLog.data || changeLog.data.items.length === 0 ? (
            <EmptyState message="No changes recorded yet." />
          ) : (
            <Table data-testid="intel-changelog-table">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>When</Table.Th>
                  <Table.Th>Scope</Table.Th>
                  <Table.Th>From</Table.Th>
                  <Table.Th>To</Table.Th>
                  <Table.Th>Reason</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {changeLog.data.items.map((c: ModeChangeLog) => (
                  <Table.Tr key={c.id}>
                    <Table.Td>{dayjs(c.changed_at).format("YYYY-MM-DD HH:mm")}</Table.Td>
                    <Table.Td>{c.workflow ?? "company"}</Table.Td>
                    <Table.Td>{c.previous_mode}</Table.Td>
                    <Table.Td>{c.new_mode}</Table.Td>
                    <Table.Td>{c.reason}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Stack>
      </Card>

      <Modal
        opened={ackModalOpen}
        onClose={() => setAckModalOpen(false)}
        title="Confirm Autonomous mode"
        data-testid="intel-ack-modal"
      >
        <Stack>
          <Alert color={colors.pending}>
            Autonomous mode allows the system to execute eligible decisions
            without waiting for HR — but only for workflows that are
            implemented, tested and explicitly authorised. No workflow can
            execute autonomously today.
          </Alert>
          <Checkbox
            checked={ack}
            onChange={(e) => setAck(e.currentTarget.checked)}
            label="I acknowledge that Autonomous mode may execute eligible decisions without waiting for HR."
            data-testid="intel-ack-checkbox"
          />
          <Group justify="flex-end">
            <Button
              onClick={onAckConfirm}
              disabled={!ack}
              data-testid="intel-ack-confirm"
            >
              Confirm acknowledgement
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
''', encoding="utf-8")
print("wrote pages/setup/IntelligenceSettingsPage.tsx")

# ---------- 3. Patch SetupLayout ----------
layout = FE / "pages" / "setup" / "SetupLayout.tsx"
s = layout.read_text(encoding="utf-8")
if "intelligence" in s:
    print("SetupLayout.tsx: already has intelligence tab")
else:
    s = s.replace(
        '  { value: "devices", label: strings.devices.title, path: "/setup/devices" },\n',
        '  { value: "devices", label: strings.devices.title, path: "/setup/devices" },\n'
        '  { value: "intelligence", label: "Intelligence", path: "/setup/intelligence" },\n',
        1,
    )
    layout.write_text(s, encoding="utf-8")
    print("SetupLayout.tsx: intelligence tab added")

# ---------- 4. Patch App.tsx ----------
app = FE / "App.tsx"
s = app.read_text(encoding="utf-8")
if "IntelligenceSettingsPage" in s:
    print("App.tsx: already has IntelligenceSettingsPage")
else:
    s = s.replace(
        'import { DevicesPage } from "./pages/setup/DevicesPage";',
        'import { DevicesPage } from "./pages/setup/DevicesPage";\n'
        'import { IntelligenceSettingsPage } from "./pages/setup/IntelligenceSettingsPage";',
        1,
    )
    s = s.replace(
        '<Route path="devices" element={<DevicesPage />} />',
        '<Route path="devices" element={<DevicesPage />} />\n'
        '            <Route path="intelligence" element={<IntelligenceSettingsPage />} />',
        1,
    )
    app.write_text(s, encoding="utf-8")
    print("App.tsx: intelligence route added")

# ---------- 5. Patch strings.ts ----------
st = FE / "lib" / "strings.ts"
s = st.read_text(encoding="utf-8")
if "intelligence: {" in s:
    print("strings.ts: already has intelligence block")
else:
    m = re.search(r"export const strings = \{\n", s)
    if not m:
        raise SystemExit("FATAL: strings export not found")
    block = (
        '  intelligence: {\n'
        '    title: "Intelligence settings",\n'
        '    subtitle: "Configure how much authority the system has over HR decisions.",\n'
        '  },\n'
    )
    s = s[:m.end()] + block + s[m.end():]
    st.write_text(s, encoding="utf-8")
    print("strings.ts: intelligence block added")

print("\nP1A stage 5 complete (frontend page + patches).")