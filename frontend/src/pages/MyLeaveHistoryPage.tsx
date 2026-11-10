import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  Alert, Badge, Button, Group, Loader, SegmentedControl, Stack,
  Table, Text, Title,
} from "@mantine/core";
import dayjs from "dayjs";
import { useMe } from "../auth/useMe";
import { fetchLeaveTypes } from "../api/leaveTypes";
import { fetchLeaveRequests, type LeaveRequestOut } from "../api/leaveRequests";

const PAGE_SIZE = 25;

const STATUS_OPTIONS = [
  { label: "All", value: "all" },
  { label: "Draft", value: "draft" },
  { label: "Submitted", value: "submitted" },
  { label: "Approved", value: "approved" },
  { label: "Rejected", value: "rejected" },
  { label: "Cancelled", value: "cancelled" },
];

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

export function MyLeaveHistoryPage() {
  const me = useMe();
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const employeeId = me.data?.employee_id ?? null;

  const types = useQuery({
    queryKey: ["leave_types"],
    queryFn: fetchLeaveTypes,
    staleTime: 5 * 60 * 1000,
    enabled: !!employeeId,
  });

  const requests = useInfiniteQuery({
    queryKey: ["leave_requests", employeeId, "history", statusFilter],
    queryFn: ({ pageParam }) =>
      fetchLeaveRequests({
        employee_id: employeeId!,
        status: statusFilter === "all" ? undefined : statusFilter,
        limit: PAGE_SIZE,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
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
    return <Loader data-testid="my-leave-history-loading" />;
  }
  if (!employeeId) {
    return (
      <Alert color="yellow" data-testid="my-leave-history-no-employee">
        Your account is not linked to an employee record.
      </Alert>
    );
  }

  const items: LeaveRequestOut[] =
    requests.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <Stack gap="md" data-testid="my-leave-history-page">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>My Leave History</Title>
          <Text size="sm" c="dimmed">
            All of your leave applications.
          </Text>
        </div>
        <Button
          variant="default"
          component={Link}
          to="/leave"
          data-testid="my-leave-history-back-link"
        >
          ← Back to My Leave
        </Button>
      </Group>

      <SegmentedControl
        value={statusFilter}
        onChange={setStatusFilter}
        data={STATUS_OPTIONS}
        data-testid="my-leave-history-status-filter"
      />

      {requests.isPending && <Loader data-testid="history-loading" />}
      {requests.isError && (
        <Alert color="red" data-testid="history-error">
          Could not load your leave history.
        </Alert>
      )}
      {requests.isSuccess && items.length === 0 && (
        <Text c="dimmed" data-testid="history-empty">
          No leave applications match this filter.
        </Text>
      )}
      {requests.isSuccess && items.length > 0 && (
        <Table data-testid="history-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Type</Table.Th>
              <Table.Th>From</Table.Th>
              <Table.Th>To</Table.Th>
              <Table.Th>Days</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Submitted</Table.Th>
              <Table.Th>Decided</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((r) => (
              <Table.Tr key={r.id} data-testid={`history-row-${r.id}`}>
                <Table.Td>
                  {typeNameById.get(r.leave_type_id) ?? "—"}
                </Table.Td>
                <Table.Td>{r.from_date}</Table.Td>
                <Table.Td>{r.to_date}</Table.Td>
                <Table.Td>{fmt(r.days_requested)}</Table.Td>
                <Table.Td>
                  <Badge color={statusColor(r.status)}>{r.status}</Badge>
                </Table.Td>
                <Table.Td>
                  {r.submitted_at
                    ? dayjs(r.submitted_at).format("YYYY-MM-DD")
                    : "—"}
                </Table.Td>
                <Table.Td>
                  {r.decided_at
                    ? dayjs(r.decided_at).format("YYYY-MM-DD")
                    : "—"}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      {requests.hasNextPage && (
        <Group justify="center">
          <Button
            variant="default"
            onClick={() => requests.fetchNextPage()}
            loading={requests.isFetchingNextPage}
            data-testid="history-load-more"
          >
            Load more
          </Button>
        </Group>
      )}
    </Stack>
  );
}