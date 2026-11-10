import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Button, Group, Modal, Select, Stack, Text, Textarea,
  TextInput,
} from "@mantine/core";
import {
  LeaveApiError, fetchLeaveTypes, type LeaveTypeOut,
} from "../../api/leaveTypes";
import {
  fetchLeaveBalances, type LeaveBalanceOut,
} from "../../api/leaveBalances";
import {
  createLeaveRequest, updateLeaveRequest, type LeaveRequestOut,
} from "../../api/leaveRequests";

function fmt(s: string): string {
  const n = Number(s);
  return Number.isFinite(n) ? n.toFixed(2) : s;
}

function mapLeaveError(code: string, status: number): string {
  if (code === "forbidden") return "You do not have permission to save this draft.";
  if (code === "not_found") return "Leave type not found. Please pick another.";
  if (code === "no_working_days_in_range" || code === "no_working_days") {
    return "The selected date range contains no working days.";
  }
  if (code === "invalid_range") {
    return "End date must be on or after the start date.";
  }
  if (code === "record_changed") {
    return "This request was changed by another user. Reload and try again.";
  }
  if (code === "not_draft") {
    return "This request is no longer editable.";
  }
  if (status === 422) return "Please check your input and try again.";
  return "Could not save. Please try again.";
}

export type ApplyLeaveModalProps = {
  opened: boolean;
  onClose: () => void;
  employeeId: string;
  onCreated: () => void;
  initialRequest?: LeaveRequestOut;
};

export function ApplyLeaveModal({
  opened, onClose, employeeId, onCreated, initialRequest,
}: ApplyLeaveModalProps) {
  const qc = useQueryClient();
  const isEdit = !!initialRequest;
  const [leaveTypeId, setLeaveTypeId] = useState<string | null>(null);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const rowVersionAtOpen = useRef<number | null>(null);

  const types = useQuery({
    queryKey: ["leave_types"],
    queryFn: fetchLeaveTypes,
    staleTime: 5 * 60 * 1000,
    enabled: opened,
  });
  const balances = useQuery({
    queryKey: ["leave_balances", employeeId],
    queryFn: () => fetchLeaveBalances({ employee_id: employeeId, limit: 50 }),
    staleTime: 30 * 1000,
    enabled: opened && !isEdit,
  });

  useEffect(() => {
    if (!opened) {
      setLeaveTypeId(null);
      setFromDate("");
      setToDate("");
      setReason("");
      setFormError(null);
      rowVersionAtOpen.current = null;
      return;
    }
    if (initialRequest) {
      setLeaveTypeId(initialRequest.leave_type_id);
      setFromDate(initialRequest.from_date);
      setToDate(initialRequest.to_date);
      setReason(initialRequest.reason ?? "");
      setFormError(null);
      rowVersionAtOpen.current = initialRequest.row_version;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, initialRequest?.id]);

  const typeOptions = useMemo(
    () =>
      (types.data?.items ?? [])
        .filter((t: LeaveTypeOut) => t.is_active)
        .map((t) => ({ value: t.id, label: `${t.name} (${t.code})` })),
    [types.data],
  );

  const selectedBalance: LeaveBalanceOut | undefined = useMemo(
    () =>
      isEdit
        ? undefined
        : (balances.data?.items ?? []).find(
            (b) => b.leave_type_id === leaveTypeId,
          ),
    [balances.data, leaveTypeId, isEdit],
  );

  const save = useMutation({
    mutationFn: async () => {
      if (initialRequest) {
        return updateLeaveRequest(initialRequest.id, {
          row_version: rowVersionAtOpen.current ?? initialRequest.row_version,
          from_date: fromDate,
          to_date: toDate,
          reason: reason.trim() ? reason : null,
        });
      }
      return createLeaveRequest({
        employee_id: employeeId,
        leave_type_id: leaveTypeId!,
        from_date: fromDate,
        to_date: toDate,
        reason: reason.trim() ? reason : null,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave_requests", employeeId, "recent"] });
      qc.invalidateQueries({ queryKey: ["leave_requests", employeeId, "history"] });
      qc.invalidateQueries({ queryKey: ["leave_balances", employeeId] });
      if (initialRequest) {
        qc.invalidateQueries({ queryKey: ["leave_request", initialRequest.id] });
      }
      onCreated();
      onClose();
    },
    onError: (err) => {
      const code = err instanceof LeaveApiError ? err.code : "unknown";
      const status = err instanceof LeaveApiError ? err.status : 0;
      setFormError(mapLeaveError(code, status));
    },
  });

  const submitDraft = () => {
    setFormError(null);
    if (!leaveTypeId) {
      setFormError("Please select a leave type.");
      return;
    }
    if (!fromDate || !toDate) {
      setFormError("Please select a start and end date.");
      return;
    }
    if (fromDate > toDate) {
      setFormError("End date must be on or after the start date.");
      return;
    }
    if (reason.length > 1000) {
      setFormError("Reason must be 1000 characters or fewer.");
      return;
    }
    save.mutate();
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={isEdit ? "Edit leave draft" : "Apply for leave"}
      size="lg"
    >
      <Stack gap="sm">
        <Select
          label="Leave type"
          placeholder="— choose leave type —"
          data={typeOptions}
          value={leaveTypeId}
          onChange={isEdit ? undefined : setLeaveTypeId}
          searchable={!isEdit}
          disabled={isEdit}
          data-testid="apply-leave-type"
          required
        />

        {selectedBalance && (
          <Text size="sm" c="dimmed" data-testid="apply-leave-balance-hint">
            Available: {fmt(selectedBalance.available)}{" "}
            {Number(selectedBalance.available) === 1 ? "day" : "days"}
            {" · "}
            Pending: {fmt(selectedBalance.pending)}
          </Text>
        )}

        <TextInput
          type="date"
          label="From"
          value={fromDate}
          onChange={(e) => setFromDate(e.currentTarget.value)}
          data-testid="apply-leave-from"
          required
        />
        <TextInput
          type="date"
          label="To"
          value={toDate}
          onChange={(e) => setToDate(e.currentTarget.value)}
          data-testid="apply-leave-to"
          required
        />
        <Text size="xs" c="dimmed">
          Exact days are calculated by the server based on your work pattern
          and calendar.
        </Text>

        <Textarea
          label="Reason (optional)"
          value={reason}
          onChange={(e) => setReason(e.currentTarget.value)}
          minRows={3}
          maxLength={1000}
          data-testid="apply-leave-reason"
        />

        {formError && (
          <Alert color="red" data-testid="apply-leave-error">
            {formError}
          </Alert>
        )}

        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={save.isPending}>
            Cancel
          </Button>
          <Button
            data-testid="apply-leave-save-draft"
            loading={save.isPending}
            onClick={submitDraft}
          >
            {isEdit ? "Save changes" : "Save draft"}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}