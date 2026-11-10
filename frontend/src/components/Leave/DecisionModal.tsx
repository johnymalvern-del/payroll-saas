import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Button, Group, Modal, Stack, Text, Textarea,
} from "@mantine/core";
import { LeaveApiError } from "../../api/leaveTypes";
import {
  decideStep,
  type LeaveApprovalStepOut,
  type LeaveRequestOut,
} from "../../api/leaveRequests";

type Props = {
  opened: boolean;
  onClose: () => void;
  mode: "approve" | "reject";
  request: LeaveRequestOut;
  step: LeaveApprovalStepOut;
  onSuccess: () => void;
};

function fmt(s: string): string {
  const n = Number(s);
  return Number.isFinite(n) ? n.toFixed(2) : s;
}

export function mapDecisionError(err: unknown): string {
  const code = err instanceof LeaveApiError ? err.code : "unknown";
  switch (code) {
    case "self_approval_forbidden":
      return "You cannot approve your own leave request.";
    case "wrong_approver":
      return "You are not the assigned approver for this step.";
    case "wrong_step":
      return "This step is no longer the current pending step. Reload the page and try again.";
    case "step_already_decided":
      return "This step has already been decided. Reload the page.";
    case "capture_requires_note":
      return "A note is required when approving your own captured leave.";
    case "record_changed":
      return "The request was updated by another user. Reload and try again.";
    case "forbidden":
      return "You do not have permission to perform this action.";
    case "not_found":
      return "Leave request not found.";
    default:
      return "Something went wrong. Please try again.";
  }
}

export function DecisionModal({
  opened,
  onClose,
  mode,
  request,
  step,
  onSuccess,
}: Props) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const isReject = mode === "reject";
  const trimmed = note.trim();
  const canSubmit = isReject ? trimmed.length > 0 : true;

  const mut = useMutation({
    mutationFn: () =>
      decideStep(request.id, step.id, {
        approve: !isReject,
        note: trimmed.length > 0 ? trimmed : null,
      }),
    onSuccess: () => {
      setError(null);
      qc.invalidateQueries({ queryKey: ["leave_request", request.id] });
      qc.invalidateQueries({ queryKey: ["leave_requests"] });
      qc.invalidateQueries({ queryKey: ["leave_balances"] });
      onSuccess();
    },
    onError: (err) => setError(mapDecisionError(err)),
  });

  const close = () => {
    if (mut.isPending) return;
    setNote("");
    setError(null);
    onClose();
  };

  const employeeLine = request.employee_name
    ? `${request.employee_name}${request.employee_code ? ` (${request.employee_code})` : ""}`
    : request.employee_code ?? "—";

  return (
    <Modal
      opened={opened}
      onClose={close}
      title={isReject ? "Reject leave request" : "Approve leave request"}
      centered
    >
      <Stack gap="sm" data-testid="decision-modal">
        <Text size="sm">
          <b>Employee:</b> {employeeLine}
        </Text>
        <Text size="sm">
          <b>Type:</b> {request.leave_type_name ?? "—"}
        </Text>
        <Text size="sm" data-testid="decision-modal-dates">
          <b>Dates:</b> {request.from_date} → {request.to_date} ·{" "}
          {fmt(request.days_requested)}{" "}
          {Number(request.days_requested) === 1 ? "day" : "days"}
        </Text>
        {request.reason && (
          <Text size="sm">
            <b>Reason:</b> {request.reason}
          </Text>
        )}
        <Text size="sm">
          <b>Step:</b> {step.step_no} · {step.approver_role ?? "unknown"}
        </Text>

        <Textarea
          label={
            isReject
              ? "Rejection reason (required, max 1000)"
              : "Note (optional, max 1000)"
          }
          value={note}
          onChange={(e) => setNote(e.currentTarget.value)}
          maxLength={1000}
          minRows={3}
          data-testid="decision-modal-note"
        />

        {error && (
          <Alert color="red" data-testid="decision-modal-error">
            {error}
          </Alert>
        )}

        <Group justify="flex-end">
          <Button
            variant="default"
            onClick={close}
            disabled={mut.isPending}
            data-testid="decision-modal-cancel"
          >
            Cancel
          </Button>
          <Button
            color={isReject ? "red" : undefined}
            loading={mut.isPending}
            disabled={!canSubmit}
            onClick={() => mut.mutate()}
            data-testid="decision-modal-confirm"
          >
            {isReject ? "Reject" : "Approve"}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}