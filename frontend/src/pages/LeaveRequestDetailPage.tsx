import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Badge, Button, Card, Grid, Group, Loader, Stack, Text,
  Timeline, Title,
} from "@mantine/core";
import dayjs from "dayjs";
import { useMe } from "../auth/useMe";
import { LeaveApiError, fetchLeaveTypes } from "../api/leaveTypes";
import {
  cancelLeaveRequest, fetchLeaveRequest, submitLeaveRequest,
  type LeaveRequestOut,
} from "../api/leaveRequests";
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

function stepColor(status: string): string {
  switch (status) {
    case "approved": return "green";
    case "rejected": return "red";
    case "pending": return "blue";
    default: return "gray";
  }
}

function mapActionError(
  err: unknown, context: "submit" | "cancel",
): string {
  const code = err instanceof LeaveApiError ? err.code : "unknown";
  const details = (err instanceof LeaveApiError ? err.details : {}) ?? {};
  if (code === "insufficient_balance") {
    return `Insufficient balance: ${String(details.available ?? "?")} available, ` +
      `${String(details.requested ?? "?")} requested.`;
  }
  if (code === "day_locked") {
    const dates = (details.dates as string[] | undefined) ?? [];
    return `Some dates are locked in a closed pay period: ${dates.join(", ")}.`;
  }
  if (code === "no_eligible_approver") {
    return "No approver is available for this leave type. Contact your HR administrator.";
  }
  if (code === "cannot_cancel_after_days_taken") {
    const dates = (details.started_days as string[] | undefined) ?? [];
    return `Cannot cancel: leave has already started on ${dates.join(", ")}.`;
  }
  if (code === "cannot_cancel") {
    return "This request can no longer be cancelled.";
  }
  if (code === "not_draft") {
    return context === "submit"
      ? "This request is no longer a draft."
      : "This request cannot be cancelled.";
  }
  if (code === "record_changed") {
    return "This request was updated by another user. Reload and try again.";
  }
  if (code === "unit_not_supported_yet") {
    return "This leave type is not currently supported for submission.";
  }
  if (code === "forbidden") {
    return "You do not have permission to perform this action.";
  }
  if (code === "not_found") {
    return "Leave request not found.";
  }
  return "Something went wrong. Please try again.";
}

export function LeaveRequestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const me = useMe();
  const employeeId = me.data?.employee_id ?? null;
  const [editOpen, setEditOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const request = useQuery({
    queryKey: ["leave_request", id],
    queryFn: () => fetchLeaveRequest(id!),
    enabled: !!id && !!employeeId,
  });
  const types = useQuery({
    queryKey: ["leave_types"],
    queryFn: fetchLeaveTypes,
    staleTime: 5 * 60 * 1000,
    enabled: !!employeeId,
  });

  const typeName = useMemo(() => {
    const lt = types.data?.items.find(
      (t) => t.id === request.data?.leave_type_id,
    );
    return lt?.name ?? null;
  }, [types.data, request.data]);

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["leave_request", id] });
    qc.invalidateQueries({ queryKey: ["leave_requests"] });
    qc.invalidateQueries({ queryKey: ["leave_balances", employeeId] });
  };

  const submitMut = useMutation({
    mutationFn: () => submitLeaveRequest(id!),
    onSuccess: () => {
      setActionError(null);
      invalidateAll();
    },
    onError: (err) => setActionError(mapActionError(err, "submit")),
  });

  const cancelMut = useMutation({
    mutationFn: () => cancelLeaveRequest(id!),
    onSuccess: () => {
      setActionError(null);
      invalidateAll();
    },
    onError: (err) => setActionError(mapActionError(err, "cancel")),
  });

  if (me.isLoading || request.isLoading || types.isLoading) {
    return <Loader data-testid="leave-request-loading" />;
  }
  if (!employeeId) {
    return (
      <Alert color="yellow" data-testid="leave-request-no-employee">
        Your account is not linked to an employee record.
      </Alert>
    );
  }
  if (request.isError || !request.data) {
    return (
      <Stack gap="sm" data-testid="leave-request-error-stack">
        <Alert color="red" data-testid="leave-request-error">
          Could not load this leave request.
        </Alert>
        <Button variant="default" onClick={() => request.refetch()}>
          Retry
        </Button>
      </Stack>
    );
  }

  const r: LeaveRequestOut = request.data;
  const isDraft = r.status === "draft";
  const isSubmitted = r.status === "submitted";
  const isApproved = r.status === "approved";
  const isRejected = r.status === "rejected";
  const isCancelled = r.status === "cancelled";

  const onEdit = () => setEditOpen(true);

  const onSubmit = () => {
    if (!window.confirm(
      "Submit this leave application for approval? " +
      "You will not be able to edit it after submitting.",
    )) return;
    submitMut.mutate();
  };

  const onCancel = () => {
    let msg = "";
    if (isDraft) {
      msg = "Cancel this draft? It cannot be recovered.";
    } else if (isSubmitted) {
      msg = `Withdraw this submitted application? ${fmt(r.days_requested)} ` +
        "day(s) of pending leave will be released.";
    } else if (isApproved) {
      msg = `Cancel approved leave? ${fmt(r.days_requested)} day(s) of ` +
        "taken leave will be reversed and your attendance will be updated. " +
        "Cannot be done if leave has already started.";
    } else {
      return;
    }
    if (!window.confirm(msg)) return;
    cancelMut.mutate();
  };

  return (
    <Stack gap="md" data-testid="leave-request-detail-page">
      <Text size="sm" c="dimmed">
        <Link to="/leave/history" data-testid="leave-request-back-link">
          ← Back to leave history
        </Link>
      </Text>

      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2} data-testid="leave-request-title">
            {typeName ?? "Leave request"}
          </Title>
          <Text size="sm" c="dimmed" data-testid="leave-request-dates">
            {r.from_date} → {r.to_date} · {fmt(r.days_requested)}{" "}
            {Number(r.days_requested) === 1 ? "day" : "days"}
          </Text>
        </div>
        <Badge
          color={statusColor(r.status)}
          size="lg"
          data-testid="leave-request-status"
        >
          {r.status}
        </Badge>
      </Group>

      {actionError && (
        <Alert color="red" data-testid="leave-request-action-error" withCloseButton
          onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      <Grid>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Card withBorder padding="md">
            <Stack gap="xs">
              <Title order={4}>Details</Title>
              <Group gap="xs">
                <Text fw={500}>From:</Text>
                <Text>{r.from_date}</Text>
              </Group>
              <Group gap="xs">
                <Text fw={500}>To:</Text>
                <Text>{r.to_date}</Text>
              </Group>
              <Group gap="xs">
                <Text fw={500}>Days requested:</Text>
                <Text>{fmt(r.days_requested)}</Text>
              </Group>
              <Group gap="xs">
                <Text fw={500}>Reason:</Text>
                <Text>{r.reason ?? "—"}</Text>
              </Group>
              <Group gap="xs">
                <Text fw={500}>Submitted:</Text>
                <Text>
                  {r.submitted_at
                    ? dayjs(r.submitted_at).format("YYYY-MM-DD HH:mm")
                    : "—"}
                </Text>
              </Group>
              <Group gap="xs">
                <Text fw={500}>Decided:</Text>
                <Text>
                  {r.decided_at
                    ? dayjs(r.decided_at).format("YYYY-MM-DD HH:mm")
                    : "—"}
                </Text>
              </Group>
              {r.decision_note && (
                <Group gap="xs" align="flex-start">
                  <Text fw={500}>Decision note:</Text>
                  <Text>{r.decision_note}</Text>
                </Group>
              )}
            </Stack>
          </Card>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 5 }}>
          <Card withBorder padding="md">
            <Stack gap="sm">
              <Title order={4}>Approval</Title>
              {r.steps.length === 0 ? (
                <Text c="dimmed" data-testid="leave-request-no-steps">
                  {isDraft
                    ? "Submit this request to start the approval chain."
                    : "No approval steps (auto-approved leave type)."}
                </Text>
              ) : (
                <Timeline
                  active={r.steps.findIndex((s) => s.status === "pending")}
                  bulletSize={18}
                  lineWidth={2}
                  data-testid="leave-request-timeline"
                >
                  {r.steps.map((s) => (
                    <Timeline.Item
                      key={s.id}
                      title={`Step ${s.step_no} · ${s.approver_role ?? "unknown"}`}
                      color={stepColor(s.status)}
                      data-testid={`leave-request-step-${s.step_no}`}
                    >
                      <Badge size="sm" color={stepColor(s.status)} variant="light">
                        {s.status}
                      </Badge>
                      {s.decided_at && (
                        <Text size="xs" c="dimmed" mt={4}>
                          Decided {dayjs(s.decided_at).format("YYYY-MM-DD HH:mm")}
                        </Text>
                      )}
                      {s.note && (
                        <Text size="sm" mt={4}>
                          {s.note}
                        </Text>
                      )}
                    </Timeline.Item>
                  ))}
                </Timeline>
              )}
            </Stack>
          </Card>
        </Grid.Col>
      </Grid>

      {(isDraft || isSubmitted || isApproved) && (
        <Group justify="flex-end" data-testid="leave-request-actions">
          {isDraft && (
            <>
              <Button
                variant="default"
                data-testid="leave-request-edit"
                onClick={onEdit}
              >
                Edit
              </Button>
              <Button
                data-testid="leave-request-submit"
                loading={submitMut.isPending}
                disabled={cancelMut.isPending}
                onClick={onSubmit}
              >
                Submit
              </Button>
            </>
          )}
          <Button
            variant="default"
            color="red"
            data-testid="leave-request-cancel"
            loading={cancelMut.isPending}
            disabled={submitMut.isPending}
            onClick={onCancel}
          >
            Cancel request
          </Button>
        </Group>
      )}

      {!isDraft && !isSubmitted && !isApproved && (
        <Group justify="flex-end" data-testid="leave-request-no-actions">
          <Text size="sm" c="dimmed">
            {isRejected
              ? "This request was rejected."
              : isCancelled
              ? "This request was cancelled."
              : "No actions available."}
          </Text>
        </Group>
      )}

      {isDraft && (
        <ApplyLeaveModal
          opened={editOpen}
          onClose={() => setEditOpen(false)}
          employeeId={employeeId}
          onCreated={() => { /* invalidation done inside modal */ }}
          initialRequest={r}
        />
      )}
    </Stack>
  );
}