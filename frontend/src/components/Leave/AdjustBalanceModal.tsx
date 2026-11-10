import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Button, Group, Modal, Stack, Text, TextInput, Textarea,
} from "@mantine/core";
import dayjs from "dayjs";
import { LeaveApiError } from "../../api/leaveTypes";
import {
  adjustLeaveBalance,
  type LeaveBalanceOut,
} from "../../api/leaveBalances";

type Props = {
  opened: boolean;
  onClose: () => void;
  balance: LeaveBalanceOut;
  employeeLabel: string;
  leaveTypeLabel: string;
  onSuccess: () => void;
};

function fmt(s: string): string {
  const n = Number(s);
  return Number.isFinite(n) ? n.toFixed(2) : s;
}

export function mapAdjustError(err: unknown): string {
  const code = err instanceof LeaveApiError ? err.code : "unknown";
  switch (code) {
    case "insufficient_balance":
      return "Resulting available balance would be negative, which is not allowed for this leave type.";
    case "forbidden":
      return "You do not have permission to adjust this balance (closed cycle requires PAYROLL_FINALISE).";
    case "not_found":
      return "Employee, leave type, or balance not found.";
    default:
      return "Something went wrong. Please try again.";
  }
}

export function AdjustBalanceModal({
  opened,
  onClose,
  balance,
  employeeLabel,
  leaveTypeLabel,
  onSuccess,
}: Props) {
  const qc = useQueryClient();
  const [delta, setDelta] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const deltaNum = Number(delta);
  const reasonTrimmed = reason.trim();
  const canSubmit =
    Number.isFinite(deltaNum) && deltaNum !== 0 && reasonTrimmed.length > 0;

  const closed = dayjs(balance.cycle_end).isBefore(dayjs(), "day");

  const mut = useMutation({
    mutationFn: () =>
      adjustLeaveBalance({
        employee_id: balance.employee_id,
        leave_type_id: balance.leave_type_id,
        cycle_start: balance.cycle_start,
        delta: String(deltaNum),
        reason: reasonTrimmed,
      }),
    onSuccess: () => {
      setError(null);
      qc.invalidateQueries({ queryKey: ["leave_balances"] });
      onSuccess();
    },
    onError: (err) => setError(mapAdjustError(err)),
  });

  const close = () => {
    if (mut.isPending) return;
    setDelta("");
    setReason("");
    setError(null);
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={close}
      title="Adjust leave balance"
      centered
    >
      <Stack gap="sm" data-testid="adjust-balance-modal">
        <Text size="sm">
          <b>Employee:</b> {employeeLabel}
        </Text>
        <Text size="sm">
          <b>Leave type:</b> {leaveTypeLabel}
        </Text>
        <Text size="sm" data-testid="adjust-modal-cycle">
          <b>Cycle:</b> {dayjs(balance.cycle_start).format("YYYY-MM-DD")} →{" "}
          {dayjs(balance.cycle_end).format("YYYY-MM-DD")}
        </Text>
        <Text size="sm">
          <b>Current available:</b> {fmt(balance.available)}
        </Text>

        {closed && (
          <Alert color="orange" data-testid="adjust-modal-closed-warning">
            This cycle is closed. Adjustment requires PAYROLL_FINALISE
            permission.
          </Alert>
        )}

        <TextInput
          label="Delta (positive to increase, negative to decrease)"
          value={delta}
          onChange={(e) => setDelta(e.currentTarget.value)}
          placeholder="e.g. 5 or -2.5"
          data-testid="adjust-modal-delta"
        />

        <Textarea
          label="Reason (required, max 1000)"
          value={reason}
          onChange={(e) => setReason(e.currentTarget.value)}
          maxLength={1000}
          minRows={3}
          data-testid="adjust-modal-reason"
        />

        {error && (
          <Alert color="red" data-testid="adjust-modal-error">
            {error}
          </Alert>
        )}

        <Group justify="flex-end">
          <Button
            variant="default"
            onClick={close}
            disabled={mut.isPending}
            data-testid="adjust-modal-cancel"
          >
            Cancel
          </Button>
          <Button
            loading={mut.isPending}
            disabled={!canSubmit}
            onClick={() => mut.mutate()}
            data-testid="adjust-modal-confirm"
          >
            Apply
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}