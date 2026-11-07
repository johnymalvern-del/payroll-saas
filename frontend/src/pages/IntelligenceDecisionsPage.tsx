import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Drawer,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import dayjs from "dayjs";
import {
  intelligenceApi,
  type DecisionDetail,
  type DecisionSummary,
} from "../api/intelligence";
import { PageHeader } from "../components/layout/PageHeader";
import { EmptyState } from "../components/layout/EmptyState";
import { TableSkeleton } from "../components/layout/TableSkeleton";
import { colors } from "../theme/colors";

export function IntelligenceDecisionsPage() {
  const [workflow, setWorkflow] = useState("");
  const [status, setStatus] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["intelligence", "decisions", workflow, status],
    queryFn: () =>
      intelligenceApi.listDecisions({
        workflow: workflow || undefined,
        status: status || undefined,
        limit: 100,
      }),
    staleTime: 30_000,
  });

  const detail = useQuery({
    queryKey: ["intelligence", "decision", selectedId],
    queryFn: () => intelligenceApi.getDecision(selectedId!),
    enabled: !!selectedId,
    staleTime: 30_000,
  });

  const verify = useQuery({
    queryKey: ["intelligence", "decision", selectedId, "verify"],
    queryFn: () => intelligenceApi.verifyDecisionSnapshot(selectedId!),
    enabled: !!selectedId,
    staleTime: Infinity,
  });

  return (
    <Stack>
      <PageHeader
        title="Decision records"
        subtitle="Read-only inspection of every intelligence decision record and its immutable evidence snapshot."
      />

      <Card>
        <Group gap="sm" wrap="wrap">
          <TextInput
            label="Workflow"
            placeholder="e.g. leave_decision"
            value={workflow}
            onChange={(e) => setWorkflow(e.currentTarget.value)}
            data-testid="decisions-filter-workflow"
            w={220}
          />
          <TextInput
            label="Status"
            placeholder="e.g. pending"
            value={status}
            onChange={(e) => setStatus(e.currentTarget.value)}
            data-testid="decisions-filter-status"
            w={180}
          />
        </Group>
      </Card>

      {list.isLoading ? (
        <TableSkeleton rows={6} cols={6} />
      ) : list.isError ? (
        <Alert color={colors.problem}>
          Could not load decision records.{" "}
          {(list.error as Error | undefined)?.message?.includes("403")
            ? "You do not have permission."
            : ""}
        </Alert>
      ) : !list.data || list.data.items.length === 0 ? (
        <EmptyState message="No decision records yet." />
      ) : (
        <Table data-testid="decisions-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>When</Table.Th>
              <Table.Th>Workflow</Table.Th>
              <Table.Th>Type</Table.Th>
              <Table.Th>Initiator</Table.Th>
              <Table.Th>Mode</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {list.data.items.map((d: DecisionSummary) => (
              <Table.Tr key={d.id}>
                <Table.Td>{dayjs(d.created_at).format("YYYY-MM-DD HH:mm")}</Table.Td>
                <Table.Td>{d.workflow}</Table.Td>
                <Table.Td>
                  <Badge variant="light" color={colors.info}>
                    {d.decision_type}
                  </Badge>
                </Table.Td>
                <Table.Td>{d.initiator_type}</Table.Td>
                <Table.Td>{d.effective_workflow_mode ?? "—"}</Table.Td>
                <Table.Td>
                  <Badge variant="light" color={colors.pending}>
                    {d.execution_status}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Button
                    size="xs"
                    variant="light"
                    onClick={() => setSelectedId(d.id)}
                  >
                    View
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Drawer
        opened={!!selectedId}
        onClose={() => setSelectedId(null)}
        position="right"
        size="lg"
        title="Decision record"
      >
        {detail.isLoading ? (
          <Loader />
        ) : detail.isError || !detail.data ? (
          <Alert color={colors.problem}>Could not load decision.</Alert>
        ) : (
          <Stack gap="md">
            <Stack gap={2}>
              <Text fw={600}>{detail.data.workflow}</Text>
              <Text size="sm" c="dimmed">
                {detail.data.id}
              </Text>
            </Stack>

            <Group gap="xs">
              <Badge variant="light">{detail.data.decision_type}</Badge>
              <Badge variant="light">{detail.data.initiator_type}</Badge>
              <Badge variant="light">{detail.data.execution_status}</Badge>
            </Group>

            <Group gap="lg">
              <Stack gap={0}>
                <Text size="xs" c="dimmed">Company mode</Text>
                <Text>{detail.data.company_default_mode ?? "—"}</Text>
              </Stack>
              <Stack gap={0}>
                <Text size="xs" c="dimmed">Effective mode</Text>
                <Text>{detail.data.effective_workflow_mode ?? "—"}</Text>
              </Stack>
              <Stack gap={0}>
                <Text size="xs" c="dimmed">Override</Text>
                <Text>{detail.data.workflow_override_mode ?? "—"}</Text>
              </Stack>
            </Group>

            {detail.data.explanation ? (
              <Stack gap={2}>
                <Text size="sm" fw={500}>Explanation</Text>
                <Text size="sm">{detail.data.explanation}</Text>
              </Stack>
            ) : null}

            {detail.data.recommendation ? (
              <Stack gap={2}>
                <Text size="sm" fw={500}>Recommendation</Text>
                <Code block>{JSON.stringify(detail.data.recommendation, null, 2)}</Code>
              </Stack>
            ) : null}

            {detail.data.snapshot ? (
              <Stack gap={2}>
                <Text size="sm" fw={500}>Evidence snapshot</Text>
                <Text size="xs" c="dimmed">
                  SHA-256: {detail.data.snapshot.sha256_hex}
                </Text>
                <Code block>{JSON.stringify(detail.data.snapshot.payload, null, 2)}</Code>
                {verify.data ? (
                  <Alert
                    color={verify.data.valid ? colors.approved : colors.problem}
                    data-testid="decisions-verify-result"
                  >
                    {verify.data.valid
                      ? "Snapshot integrity verified."
                      : "Snapshot integrity FAILED."}
                  </Alert>
                ) : null}
              </Stack>
            ) : (
              <Alert color={colors.inactive}>No snapshot attached.</Alert>
            )}
          </Stack>
        )}
      </Drawer>
    </Stack>
  );
}
