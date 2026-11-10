import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Alert, Badge, Button, Card, Group, Loader, SimpleGrid, Stack,
  Table, Text, Title,
} from "@mantine/core";
import dayjs from "dayjs";
import { useMe } from "../auth/useMe";
import { fetchLeaveTypes, type LeaveTypeOut } from "../api/leaveTypes";
import { fetchLeaveBalances } from "../api/leaveBalances";
import { fetchLeaveRequests, type LeaveRequestOut } from "../api/leaveRequests";
import { ApplyLeaveModal } from "../components/Leave/ApplyLeaveModal";

function fmt(s: string): string {
  const n = Number(s);
  return Number.isFinite(n) ? n.toFixed(2) : s;
}

function statusColor(s: string): string {
  switch (s) {
    case "approved": return "green";
    case "rejected": return "red";
    case "submitted": return "blue";
    case "cancelled": return "gray";
    default: return "gray";
  }
}

export function MyLeavePage() {
  const me = useMe();
  const navigate = useNavigate();
  const [applyOpen, setApplyOpen] = useState(false);

  const employeeId = me.data?.employee_id ?? null;

  const types = useQuery({
    queryKey: ["leave_types"],
    queryFn: fetchLeaveTypes,
    staleTime: 5 * 60 * 1000,
    enabled: !!employeeId,
  });

  const balances = useQuery({
    queryKey: ["leave_balances", employeeId],
    queryFn: () => fetchLeaveBalances({ employee_id: employeeId!, limit: 50 }),
    staleTime: 30 * 1000,
    enabled: !!employeeId,
  });

  const recent = useQuery({
    queryKey: ["leave_requests", employeeId, "recent"],
    queryFn: () =>
      fetchLeaveRequests({ employee_id: employeeId!, limit: 5 }),
    enabled: !!employeeId,
  });

  const typeNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of types.data?.items ?? []) {
      map.set(t.id, t.name);
    }
    return map;
  }, [types.data]);

  if (me.isLoading) {
    return <Loader data-testid="my-leave-loading" />;
  }
  if (!employeeId) {
    return (
      <Alert color="yellow" data-testid="my-leave-no-employee">
        Your account is not linked to an employee record. Ask your administrator
        to link it before applying for leave.
      </Alert>
    );
  }

  const balanceItems = balances.data?.items ?? [];
  const requestItems = recent.data?.items ?? [];

  return (
    <Stack gap="md" data-testid="my-leave-page">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>My Leave</Title>
          <Text size="sm" c="dimmed">
            Your leave balances and recent applications.
          </Text>
        </div>
        <Group gap="xs">
          <Button
            variant="default"
            component={Link}
            to="/leave/history"
            data-testid="my-leave-history-link"
          >
            View history
          </Button>
          <Button
            data-testid="my-leave-apply-button"
            onClick={() => setApplyOpen(true)}
          >
            Apply for leave
          </Button>
        </Group>
      </Group>

      {balances.data?.accrual_stale && (
        <Alert color="yellow" data-testid="my-leave-accrual-stale">
          Accruals have not been run recently. Balance figures may be out of date.
        </Alert>
      )}

      <Title order={4}>Balances</Title>
      {balances.isLoading && <Loader data-testid="balances-loading" />}
      {balances.isError && (
        <Alert color="red" data-testid="balances-error">
          Could not load your leave balances.
        </Alert>
      )}
      {balances.isSuccess && balanceItems.length === 0 && (
        <Text c="dimmed" data-testid="balances-empty">
          No leave balances are available for the current cycle.
        </Text>
      )}
      {balances.isSuccess && balanceItems.length > 0 && (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
          {balanceItems.map((b) => (
            <Card
              key={b.id}
              withBorder
              padding="md"
              data-testid={`balance-card-${b.leave_type_id}`}
            >
              <Group justify="space-between" align="center">
                <Text fw={600}>
                  {typeNameById.get(b.leave_type_id) ?? "Leave"}
                </Text>
                <Badge variant="light" size="sm">
                  {dayjs(b.cycle_start).format("MMM YYYY")}
                </Badge>
              </Group>
              <Group align="baseline" gap="xs" mt="sm">
                <Text
                  size="xl"
                  fw={700}
                  data-testid={`balance-available-${b.leave_type_id}`}
                >
                  {fmt(b.available)}
                </Text>
                <Text size="sm" c="dimmed">available</Text>
              </Group>
              <Group gap="md" mt={4}>
                <Text size="xs" c="dimmed">
                  Entitled {fmt(b.entitled)}
                </Text>
                <Text size="xs" c="dimmed">
                  Accrued {fmt(b.accrued)}
                </Text>
                <Text size="xs" c="dimmed">
                  Pending {fmt(b.pending)}
                </Text>
                <Text size="xs" c="dimmed">
                  Taken {fmt(b.taken)}
                </Text>
              </Group>
            </Card>
          ))}
        </SimpleGrid>
      )}

      <Group justify="space-between" align="center" mt="sm">
        <Title order={4}>Recent applications</Title>
        <Text
          size="sm"
          component={Link}
          to="/leave/history"
          data-testid="my-leave-history-link-inline"
        >
          View all →
        </Text>
      </Group>
      {recent.isLoading && <Loader data-testid="recent-loading" />}
      {recent.isError && (
        <Alert color="red" data-testid="recent-error">
          Could not load your recent applications.
        </Alert>
      )}
      {recent.isSuccess && requestItems.length === 0 && (
        <Text c="dimmed" data-testid="recent-empty">
          No leave applications yet. Use "Apply for leave" to create a draft.
        </Text>
      )}
      {recent.isSuccess && requestItems.length > 0 && (
        <Table data-testid="recent-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Type</Table.Th>
              <Table.Th>Dates</Table.Th>
              <Table.Th>Days</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Submitted</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {requestItems.map((r: LeaveRequestOut) => (
              <Table.Tr
                key={r.id}
                data-testid={`recent-row-${r.id}`}
                style={{ cursor: "pointer" }}
                onClick={() => navigate(`/leave/requests/${r.id}`)}
              >
                <Table.Td>
                  {typeNameById.get(r.leave_type_id) ?? "—"}
                </Table.Td>
                <Table.Td>
                  {r.from_date} → {r.to_date}
                </Table.Td>
                <Table.Td>{fmt(r.days_requested)}</Table.Td>
                <Table.Td>
                  <Badge color={statusColor(r.status)}>{r.status}</Badge>
                </Table.Td>
                <Table.Td>
                  {r.submitted_at
                    ? dayjs(r.submitted_at).format("YYYY-MM-DD")
                    : "—"}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <ApplyLeaveModal
        opened={applyOpen}
        onClose={() => setApplyOpen(false)}
        employeeId={employeeId}
        onCreated={() => {
          /* queries invalidated inside modal */
        }}
      />
    </Stack>
  );
}