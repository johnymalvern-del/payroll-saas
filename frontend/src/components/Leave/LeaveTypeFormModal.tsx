import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Button, Group, Modal, MultiSelect, NumberInput, Select, Stack,
  Switch, TextInput,
} from "@mantine/core";
import { LeaveApiError } from "../../api/leaveTypes";
import {
  createLeaveType,
  patchLeaveType,
  type LeaveTypeIn,
  type LeaveTypePatchIn,
  type LeaveTypeOut,
} from "../../api/leaveTypes";

type Props = {
  opened: boolean;
  onClose: () => void;
  initialType?: LeaveTypeOut | null;
  onSuccess: () => void;
};

const APPROVER_OPTIONS = [
  { value: "manager", label: "Manager" },
  { value: "hr", label: "HR" },
  { value: "payroll_admin", label: "Payroll admin" },
];

const UNIT_OPTIONS = [
  { value: "day", label: "Day" },
  { value: "hour", label: "Hour" },
];

const METHOD_OPTIONS = [
  { value: "none", label: "None" },
  { value: "monthly", label: "Monthly" },
  { value: "annual", label: "Annual" },
  { value: "fixed", label: "Fixed" },
];

const CYCLE_OPTIONS = [
  { value: "calendar", label: "Calendar year" },
  { value: "anniversary", label: "Anniversary" },
  { value: "fixed", label: "Fixed anchor" },
];

export function mapLeaveTypeError(err: unknown): string {
  const code = err instanceof LeaveApiError ? err.code : "unknown";
  const details = (err instanceof LeaveApiError ? err.details : {}) ?? {};
  switch (code) {
    case "duplicate_code":
      return "A leave type with that code already exists.";
    case "accrual_amount_required":
      return "An accrual amount is required for annual or fixed methods.";
    case "negative_requires_accrual":
      return "Allow-negative cannot be combined with accrual method 'none'.";
    case "carryover_not_allowed_on_fixed":
      return "Max carryover is not allowed when the cycle is 'fixed'.";
    case "leave_type_in_use":
      return "Cannot deactivate: leave balances reference this type.";
    case "record_changed": {
      const current = details.current_row_version;
      return current !== undefined
        ? `This leave type was updated by another user (current version ${current}). Reload and try again.`
        : "This leave type was updated by another user. Reload and try again.";
    }
    case "not_found":
      return "Leave type not found.";
    case "forbidden":
      return "You do not have permission to perform this action.";
    default:
      return "Something went wrong. Please try again.";
  }
}

type Form = {
  name: string;
  code: string;
  unit: string;
  paid: boolean;
  accrual_method: string;
  accrual_amount: string;
  cycle: string;
  requires_approval: boolean;
  requires_document_after_days: string;
  allow_negative: boolean;
  max_carryover: string;
  approval_chain: string[];
  requires_payroll_admin_final: boolean;
};

const EMPTY: Form = {
  name: "",
  code: "",
  unit: "day",
  paid: true,
  accrual_method: "none",
  accrual_amount: "",
  cycle: "calendar",
  requires_approval: true,
  requires_document_after_days: "",
  allow_negative: false,
  max_carryover: "",
  approval_chain: ["manager", "hr"],
  requires_payroll_admin_final: false,
};

function formFrom(t: LeaveTypeOut): Form {
  return {
    name: t.name,
    code: t.code,
    unit: t.unit,
    paid: t.paid,
    accrual_method: t.accrual_method,
    accrual_amount: t.accrual_amount ?? "",
    cycle: t.cycle,
    requires_approval: t.requires_approval,
    requires_document_after_days:
      t.requires_document_after_days != null
        ? String(t.requires_document_after_days)
        : "",
    allow_negative: t.allow_negative,
    max_carryover: t.max_carryover ?? "",
    approval_chain: [...t.approval_chain],
    requires_payroll_admin_final: t.requires_payroll_admin_final,
  };
}

export function LeaveTypeFormModal({
  opened,
  onClose,
  initialType,
  onSuccess,
}: Props) {
  const qc = useQueryClient();
  const isEdit = !!initialType;
  const [form, setForm] = useState<Form>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (!opened) return;
    setForm(initialType ? formFrom(initialType) : EMPTY);
    setError(null);
    setValidationError(null);
  }, [opened, initialType]);

  const set = <K extends keyof Form>(k: K, v: Form[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const validate = (): string | null => {
    if (!form.name.trim()) return "Name is required.";
    if (!isEdit && !form.code.trim()) return "Code is required.";
    if (
      (form.accrual_method === "annual" || form.accrual_method === "fixed") &&
      form.accrual_amount.trim() === ""
    ) {
      return "Accrual amount is required for annual or fixed methods.";
    }
    if (
      form.allow_negative &&
      form.accrual_method === "none"
    ) {
      return "Allow-negative cannot be combined with accrual method 'none'.";
    }
    if (form.cycle === "fixed" && form.max_carryover.trim() !== "") {
      return "Max carryover is not allowed when the cycle is 'fixed'.";
    }
    return null;
  };

  const buildBody = (): LeaveTypeIn => ({
    name: form.name.trim(),
    code: form.code.trim().toLowerCase(),
    unit: form.unit,
    paid: form.paid,
    accrual_method: form.accrual_method,
    accrual_amount:
      form.accrual_amount.trim() === "" ? null : form.accrual_amount.trim(),
    cycle: form.cycle,
    requires_approval: form.requires_approval,
    requires_document_after_days:
      form.requires_document_after_days.trim() === ""
        ? null
        : Number(form.requires_document_after_days),
    allow_negative: form.allow_negative,
    max_carryover:
      form.max_carryover.trim() === "" ? null : form.max_carryover.trim(),
    approval_chain: form.approval_chain,
    requires_payroll_admin_final: form.requires_payroll_admin_final,
  });

  const mut = useMutation({
    mutationFn: async () => {
      if (isEdit && initialType) {
        const body: LeaveTypePatchIn = {
          row_version: initialType.row_version,
          ...buildBody(),
        };
        // PATCH ignores `code` server-side; leaving it in is harmless but
        // cleaner to strip.
        const { ...rest } = body as LeaveTypePatchIn & { code?: string };
        delete rest.code;
        return patchLeaveType(initialType.id, rest);
      }
      return createLeaveType(buildBody());
    },
    onSuccess: () => {
      setError(null);
      qc.invalidateQueries({ queryKey: ["leave_types_admin"] });
      qc.invalidateQueries({ queryKey: ["leave_types"] });
      onSuccess();
    },
    onError: (err) => setError(mapLeaveTypeError(err)),
  });

  const submit = () => {
    const v = validate();
    if (v) {
      setValidationError(v);
      return;
    }
    setValidationError(null);
    mut.mutate();
  };

  const close = () => {
    if (mut.isPending) return;
    setError(null);
    setValidationError(null);
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={close}
      title={isEdit ? "Edit leave type" : "Create leave type"}
      size="lg"
      centered
    >
      <Stack gap="sm" data-testid="leave-type-form-modal">
        <TextInput
          label="Name"
          value={form.name}
          onChange={(e) => set("name", e.currentTarget.value)}
          maxLength={80}
          data-testid="leave-type-form-name"
        />
        <TextInput
          label="Code"
          value={form.code}
          onChange={(e) => set("code", e.currentTarget.value)}
          maxLength={30}
          disabled={isEdit}
          data-testid="leave-type-form-code"
          description={isEdit ? "Code is immutable once created." : "Stored lowercase."}
        />
        <Group grow>
          <Select
            label="Unit"
            data={UNIT_OPTIONS}
            value={form.unit}
            onChange={(v) => set("unit", v ?? "day")}
            allowDeselect={false}
            data-testid="leave-type-form-unit"
          />
          <Select
            label="Cycle"
            data={CYCLE_OPTIONS}
            value={form.cycle}
            onChange={(v) => {
              const next = v ?? "calendar";
              set("cycle", next);
              if (next === "fixed") set("max_carryover", "");
            }}
            allowDeselect={false}
            data-testid="leave-type-form-cycle"
          />
        </Group>
        <Group grow>
          <Select
            label="Accrual method"
            data={METHOD_OPTIONS}
            value={form.accrual_method}
            onChange={(v) => set("accrual_method", v ?? "none")}
            allowDeselect={false}
            data-testid="leave-type-form-accrual-method"
          />
          <TextInput
            label="Accrual amount"
            value={form.accrual_amount}
            onChange={(e) => set("accrual_amount", e.currentTarget.value)}
            placeholder="e.g. 21"
            data-testid="leave-type-form-accrual-amount"
          />
        </Group>
        <Group grow>
          <NumberInput
            label="Requires document after N days (optional)"
            value={form.requires_document_after_days === "" ? "" : Number(form.requires_document_after_days)}
            onChange={(v) =>
              set(
                "requires_document_after_days",
                v === "" || v === undefined ? "" : String(v),
              )
            }
            min={0}
            data-testid="leave-type-form-req-doc"
          />
          <TextInput
            label="Max carryover (optional)"
            value={form.max_carryover}
            onChange={(e) => set("max_carryover", e.currentTarget.value)}
            disabled={form.cycle === "fixed"}
            placeholder="e.g. 5"
            data-testid="leave-type-form-max-carryover"
          />
        </Group>
        <MultiSelect
          label="Approval chain"
          data={APPROVER_OPTIONS}
          value={form.approval_chain}
          onChange={(v) => set("approval_chain", v)}
          data-testid="leave-type-form-chain"
        />
        <Group>
          <Switch
            label="Paid"
            checked={form.paid}
            onChange={(e) => set("paid", e.currentTarget.checked)}
            data-testid="leave-type-form-paid"
          />
          <Switch
            label="Requires approval"
            checked={form.requires_approval}
            onChange={(e) => set("requires_approval", e.currentTarget.checked)}
            data-testid="leave-type-form-req-appr"
          />
          <Switch
            label="Allow negative"
            checked={form.allow_negative}
            onChange={(e) => set("allow_negative", e.currentTarget.checked)}
            data-testid="leave-type-form-allow-neg"
          />
          <Switch
            label="Requires payroll admin final"
            checked={form.requires_payroll_admin_final}
            onChange={(e) =>
              set("requires_payroll_admin_final", e.currentTarget.checked)
            }
            data-testid="leave-type-form-req-pa-final"
          />
        </Group>

        {validationError && (
          <Alert color="orange" data-testid="leave-type-form-validation">
            {validationError}
          </Alert>
        )}
        {error && (
          <Alert color="red" data-testid="leave-type-form-error">
            {error}
          </Alert>
        )}

        <Group justify="flex-end">
          <Button
            variant="default"
            onClick={close}
            disabled={mut.isPending}
            data-testid="leave-type-form-cancel"
          >
            Cancel
          </Button>
          <Button
            loading={mut.isPending}
            onClick={submit}
            data-testid="leave-type-form-confirm"
          >
            {isEdit ? "Save" : "Create"}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}