import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Loader,
  Modal,
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
  const canSave = canManage && modeChanged && reason.trim().length >= 3;

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
          {needsAck && (
            <Alert color={colors.pending} data-testid="intel-ack-pending-hint">
              Click Save to acknowledge Autonomous mode.
            </Alert>
          )}

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
