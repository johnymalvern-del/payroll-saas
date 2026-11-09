import { useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { fetchEmployees } from "../api/employees";
import {
  ChangeRequestsApiError,
  approveChangeRequest,
  cancelChangeRequest,
  fetchChangeRequests,
  rejectChangeRequest,
  type ChangeRequestOut,
} from "../api/changeRequests";
import { mapErrorCode } from "../api/errors";
import { strings } from "../lib/strings";
import { colors } from "../theme/colors";

const PAGE_SIZE = 100;

const STATUS_OPTIONS = [
  { label: strings.changeRequests.allStatuses, value: "all" },
  { label: strings.changeRequests.statusPending, value: "pending" },
  { label: strings.changeRequests.statusApproved, value: "approved" },
  { label: strings.changeRequests.statusRejected, value: "rejected" },
  { label: strings.changeRequests.statusCancelled, value: "cancelled" },
];

function statusColor(status: string): string {
  switch (status) {
    case "pending":
      return "orange";
    case "approved":
      return "green";
    case "rejected":
      return "red";
    case "cancelled":
      return "gray";
    default:
      return "gray";
  }
}

type ModalState =
  | { action: "approve"; req: ChangeRequestOut }
  | { action: "reject"; req: ChangeRequestOut }
  | { action: "cancel"; req: ChangeRequestOut }
  | null;

export function ChangeRequestsPage() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("pending");
  const [modal, setModal] = useState<ModalState>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [pageError, setPageError] = useState<string | null>(null);

  const employees = useQuery({
    queryKey: ["refs", "employees"],
    queryFn: () => fetchEmployees(),
    staleTime: 5 * 60 * 1000,
  });

  const requests = useInfiniteQuery({
    queryKey: ["change_requests", statusFilter],
    queryFn: ({ pageParam }) =>
      fetchChangeRequests({
        status: statusFilter === "all" ? undefined : statusFilter,
        cursor: pageParam,
        limit: PAGE_SIZE,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const empMap = new Map<string, { name: string; code: string }>();
  for (const e of employees.data ?? []) {
    empMap.set(e.id, {
      name: `${e.first_name} ${e.last_name}`.trim(),
      code: e.employee_code,
    });
  }

  // Assignment-linked change requests are audit envelopes controlled by the
  // salary-assignment service; they are not part of the standalone queue.
  // Filter client-side because the backend list endpoint has no
  // include_assignment_children toggle today. Records remain queryable via
  // GET /payroll/change-requests/{id} and via the salary assignment detail.
  const allItems = requests.data?.pages.flatMap((p) => p.items) ?? [];
  const items = allItems.filter((r) => r.assignment_id == null);

  const applyMutation = useMutation({
    mutationFn: async (vars: {
      action: "approve" | "reject" | "cancel";
      id: string;
      note?: string;
    }) => {
      if (vars.action === "approve") return approveChangeRequest(vars.id);
      if (vars.action === "reject") return rejectChangeRequest(vars.id, vars.note ?? "");
      return cancelChangeRequest(vars.id);
    },
    onSuccess: () => {
      setModal(null);
      setRejectNote("");
      setPageError(null);
      qc.invalidateQueries({ queryKey: ["change_requests"] });
    },
    onError: (err) => {
      const code =
        err instanceof ChangeRequestsApiError
          ? err.code
          : err instanceof Error
            ? err.message
            : undefined;
      setPageError(code ? mapErrorCode(code) : strings.genericError);
      setModal(null);
      setRejectNote("");
    },
  });

  const busyId =
    applyMutation.isPending
      ? (applyMutation.variables as { id: string } | undefined)?.id ?? null
      : null;

  const openModal = (next: NonNullable<ModalState>) => {
    setPageError(null);
    setRejectNote("");
    setModal(next);
  };

  const runApply = () => {
    if (!modal) return;
    const id = modal.req.id;
    if (modal.action === "approve") {
      applyMutation.mutate({ action: "approve", id });
    } else if (modal.action === "reject") {
      applyMutation.mutate({ action: "reject", id, note: rejectNote.trim() });
    } else {
      applyMutation.mutate({ action: "cancel", id });
    }
  };

  const rejectNoteOk = rejectNote.trim().length > 0;
  const canSubmitModal =
    !applyMutation.isPending &&
    (modal?.action !== "reject" || rejectNoteOk);

  const modalTitle =
    modal?.action === "approve"
      ? strings.changeRequests.confirmApproveTitle
      : modal?.action === "reject"
        ? strings.changeRequests.confirmRejectTitle
        : strings.changeRequests.confirmCancelTitle;

  const modalBody =
    modal?.action === "approve"
      ? strings.changeRequests.confirmApproveBody
      : modal?.action === "reject"
        ? strings.changeRequests.confirmRejectBody
        : strings.changeRequests.confirmCancelBody;

  return (
    <Stack gap="md">
      <Title order={2}>{strings.changeRequests.title}</Title>

      {pageError ? (
        <Alert
          color={colors.problem}
          withCloseButton
          onClose={() => setPageError(null)}
          data-testid="change-requests-error"
        >
          {pageError}
        </Alert>
      ) : null}

      <Paper withBorder p="md">
        <SegmentedControl
          value={statusFilter}
          onChange={(v) => setStatusFilter(v)}
          data={STATUS_OPTIONS}
          data-testid="change-requests-status-filter"
        />
      </Paper>

      <Paper withBorder p="md">
        {requests.isPending ? (
          <Group justify="center" p="xl">
            <Loader />
          </Group>
        ) : requests.isError ? (
          <Group justify="space-between" align="center">
            <Text c="red" size="sm" data-testid="change-requests-load-error">
              {strings.changeRequests.error}
            </Text>
            <Button
              size="xs"
              variant="default"
              onClick={() => requests.refetch()}
              data-testid="change-requests-retry"
            >
              {strings.common.retry}
            </Button>
          </Group>
        ) : items.length === 0 ? (
          <Text c="dimmed">{strings.changeRequests.empty}</Text>
        ) : (
          <Stack gap="sm" data-testid="change-requests-list">
            {items.map((r) => {
              const info = empMap.get(r.employee_id);
              const empName =
                info?.name || r.employee_id.slice(0, 8);
              const empCode = info?.code ?? "";
              const rowBusy = busyId === r.id;
              return (
                <Paper
                  key={r.id}
                  withBorder
                  p="sm"
                  data-testid={`change-request-${r.id}`}
                >
                  <Group justify="space-between" align="center" wrap="nowrap">
                    <Stack gap={2}>
                      <Group gap="sm">
                        <Text fw={600}>{r.kind.replace(/_/g, " ")}</Text>
                        <Badge color={statusColor(r.status)} variant="light">
                          {r.status}
                        </Badge>
                      </Group>
                      <Text size="sm">
                        {empName}
                        {empCode ? ` (${empCode})` : ""}
                      </Text>
                      <Text size="xs" c="dimmed">
                        Requested {new Date(r.requested_at).toLocaleString()}
                      </Text>
                    </Stack>
                    {r.status === "pending" ? (
                      <Group gap="xs">
                        <Button
                          size="xs"
                          onClick={() =>
                            openModal({ action: "approve", req: r })
                          }
                          loading={rowBusy}
                          disabled={rowBusy}
                          data-testid={`change-request-approve-${r.id}`}
                        >
                          {strings.changeRequests.approveButton}
                        </Button>
                        <Button
                          size="xs"
                          variant="default"
                          onClick={() =>
                            openModal({ action: "reject", req: r })
                          }
                          loading={rowBusy}
                          disabled={rowBusy}
                          data-testid={`change-request-reject-${r.id}`}
                        >
                          {strings.changeRequests.rejectButton}
                        </Button>
                        <Button
                          size="xs"
                          variant="default"
                          onClick={() =>
                            openModal({ action: "cancel", req: r })
                          }
                          loading={rowBusy}
                          disabled={rowBusy}
                          data-testid={`change-request-cancel-${r.id}`}
                        >
                          {strings.changeRequests.cancelButton}
                        </Button>
                      </Group>
                    ) : null}
                  </Group>
                </Paper>
              );
            })}
          </Stack>
        )}
      </Paper>

      {requests.hasNextPage ? (
        <Group justify="center">
          <Button
            variant="default"
            onClick={() => requests.fetchNextPage()}
            loading={requests.isFetchingNextPage}
            data-testid="change-requests-load-more"
          >
            {strings.changeRequests.loadMore}
          </Button>
        </Group>
      ) : null}

      <Modal
        opened={modal !== null}
        onClose={() => {
          if (applyMutation.isPending) return;
          setModal(null);
          setRejectNote("");
        }}
        title={modalTitle}
        data-testid="change-requests-modal"
      >
        <Stack gap="sm">
          <Text size="sm">{modalBody}</Text>
          {modal?.action === "reject" ? (
            <Textarea
              label={strings.changeRequests.rejectNoteLabel}
              value={rejectNote}
              onChange={(e) => setRejectNote(e.currentTarget.value)}
              minRows={3}
              error={
                !rejectNoteOk && rejectNote !== ""
                  ? strings.changeRequests.rejectNoteRequired
                  : undefined
              }
              required
              data-testid="change-requests-reject-note"
            />
          ) : null}
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => {
                setModal(null);
                setRejectNote("");
              }}
              disabled={applyMutation.isPending}
              data-testid="change-requests-modal-cancel"
            >
              {strings.common.cancel}
            </Button>
            <Button
              onClick={runApply}
              loading={applyMutation.isPending}
              disabled={!canSubmitModal}
              data-testid="change-requests-modal-apply"
            >
              {strings.common.confirm}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}