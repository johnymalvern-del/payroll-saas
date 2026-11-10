import { Link, useNavigate } from "react-router-dom";
import { useInfiniteQuery } from "@tanstack/react-query";
import {
  Alert, Badge, Button, Card, Group, Loader, Stack, Table, Text, Title,
} from "@mantine/core";
import dayjs from "dayjs";
import { useMe } from "../auth/useMe";
import {
  fetchLeaveRequests,
  type LeaveApprovalStepOut,
  type LeaveRequestOut,
} from "../api/leaveRequests";

function fmt(s: string): string {
  const n = Number(s);
  return Number.isFinite(n) ? n.toFixed(2) : s;
}

function currentPendingStep(r: LeaveRequestOut): LeaveApprovalStepOut | null {
  // Backend returns steps ordered by step_no; the first pending step
  // is the current one for approval. B-L4a guarantees this step belongs
  // to the caller when they arrive via awaiting_approver_user_id.
  return r.steps.find((s) => s.status === "pending") ?? null;
}

function employeeDisplay(r: LeaveRequestOut): string {
  if (r.employee_name && r.employee_code) {
    return `${r.employee_name} (${r.employee_code})`;
  }
  if (r.employee_name) return r.employee_name;
  if (r.employee_code) return r.employee_code;
  return "—";
}

export function MyApprovalsPage() {
  const me = useMe();
  const navigate = useNavigate();
  const myUserId = me.data?.id ?? null;
  const permissions = me.data?.permissions ?? [];
  const canApprove = permissions.includes("leave_approve");

  const q = useInfiniteQuery({
    queryKey: ["leave_requests", "awaiting", myUserId],
    queryFn: ({ pageParam }) =>
      fetchLeaveRequests({
        awaiting_approver_user_id: myUserId!,
        status: "submitted",
        limit: 100,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: canApprove && !!myUserId,
  });

  if (me.isLoading) {
    return <Loader data-testid="approvals-loading" />;
  }

  if (!canApprove) {
    return (
      <Alert color="yellow" data-testid="approvals-no-permission">
        You do not have permission to view leave approvals.
      </Alert>
    );
  }

  const items = q.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <Stack gap="md" data-testid="my-approvals-page">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>My Approvals</Title>
          <Text size="sm" c="dimmed">
            Leave applications awaiting your decision.
          </Text>
        </div>
        <Button
          component={Link}
          to="/leave"
          variant="default"
          data-testid="my-approvals-my-leave-link"
        >
          My Leave
        </Button>
      </Group>

      {q.isLoading && <Loader data-testid="approvals-loading-table" />}

      {q.isError && (
        <Alert color="red" data-testid="approvals-error">
          Could not load your approval queue.
        </Alert>
      )}

      {!q.isLoading && !q.isError && items.length === 0 && (
        <Alert color="blue" data-testid="approvals-empty">
          No leave requests awaiting your approval.
        </Alert>
      )}

      {items.length > 0 && (
        <Card withBorder padding="md">
          <Table data-testid="approvals-table">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Employee</Table.Th>
                <Table.Th>Type</Table.Th>
                <Table.Th>From</Table.Th>
                <Table.Th>To</Table.Th>
                <Table.Th>Days</Table.Th>
                <Table.Th>Current step</Table.Th>
                <Table.Th>Submitted</Table.Th>
                <Table.Th></Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((r) => {
                const step = currentPendingStep(r);
                return (
                  <Table.Tr key={r.id} data-testid={`approvals-row-${r.id}`}>
                    <Table.Td>{employeeDisplay(r)}</Table.Td>
                    <Table.Td>{r.leave_type_name ?? "—"}</Table.Td>
                    <Table.Td>{r.from_date}</Table.Td>
                    <Table.Td>{r.to_date}</Table.Td>
                    <Table.Td>{fmt(r.days_requested)}</Table.Td>
                    <Table.Td>
                      {step ? (
                        <Badge color="blue" variant="light">
                          {step.approver_role ?? `Step ${step.step_no}`}
                        </Badge>
                      ) : (
                        <Badge color="gray" variant="light">none pending</Badge>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {r.submitted_at
                        ? dayjs(r.submitted_at).format("YYYY-MM-DD HH:mm")
                        : "—"}
                    </Table.Td>
                    <Table.Td>
                      <Button
                        size="xs"
                        variant="light"
                        data-testid={`approvals-open-${r.id}`}
                        onClick={() =>
                          navigate(`/leave/requests/${r.id}`, {
                            state: { returnTo: "/leave/approvals" },
                          })
                        }
                      >
                        Open
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
          {q.hasNextPage && (
            <Group justify="center" mt="md">
              <Button
                variant="default"
                data-testid="approvals-load-more"
                loading={q.isFetchingNextPage}
                onClick={() => q.fetchNextPage()}
              >
                Load more
              </Button>
            </Group>
          )}
        </Card>
      )}
    </Stack>
  );
}