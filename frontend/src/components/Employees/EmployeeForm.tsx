import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Divider,
  Group,
  Modal,
  NumberInput,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  EmployeesApiError,
  createEmployee,
  fetchEmployees,
  patchEmployee,
  type EmployeeCreateIn,
  type EmployeeOut,
  type EmployeePatchIn,
} from "../../api/employees";
import { fetchBranches, fetchDepartments, fetchSites } from "../../api/attendance";
import { absoluteUrl, wrappedFetch } from "../../api/client";
import { mapErrorCode } from "../../api/errors";
import { strings } from "../../lib/strings";

const STATUSES = [
  { value: "active", label: strings.employees.statusActive },
  { value: "on_leave", label: strings.employees.statusOnLeave },
  { value: "suspended", label: strings.employees.statusSuspended },
  { value: "terminated", label: strings.employees.statusTerminated },
];

const EMPLOYEE_TYPES = ["hourly", "salaried", "casual", "contract"];
const PAY_BASES = ["hourly", "daily", "monthly"];
const PAY_FREQUENCIES = ["weekly", "fortnightly", "monthly"];

type FormState = {
  employee_code: string;
  first_name: string;
  last_name: string;
  national_id: string;
  email: string;
  mobile: string;
  date_of_birth: string;
  hire_date: string;
  termination_date: string;
  status: string;
  job_title: string;
  branch_id: string;
  site_id: string;
  department_id: string;
  manager_id: string;
  employee_type: string;
  pay_basis: string;
  pay_frequency: string;
  base_rate: string;
  overtime_eligible: boolean;
  clocks: boolean;
  work_pattern_id: string;
  default_shift_id: string;
  bank_name: string;
  bank_account_number: string;
  bank_branch_code: string;
  account_type: string;
  tax_number: string;
  medical_aid_dependants: number;
  retirement_fund_flags: string;
  uif_exempt: boolean;
  notes: string;
};

const BLANK: FormState = {
  employee_code: "",
  first_name: "",
  last_name: "",
  national_id: "",
  email: "",
  mobile: "",
  date_of_birth: "",
  hire_date: "",
  termination_date: "",
  status: "active",
  job_title: "",
  branch_id: "",
  site_id: "",
  department_id: "",
  manager_id: "",
  employee_type: "hourly",
  pay_basis: "hourly",
  pay_frequency: "monthly",
  base_rate: "",
  overtime_eligible: true,
  clocks: true,
  work_pattern_id: "",
  default_shift_id: "",
  bank_name: "",
  bank_account_number: "",
  bank_branch_code: "",
  account_type: "",
  tax_number: "",
  medical_aid_dependants: 0,
  retirement_fund_flags: "",
  uif_exempt: false,
  notes: "",
};

function fromEmployee(e: EmployeeOut): FormState {
  return {
    employee_code: e.employee_code,
    first_name: e.first_name,
    last_name: e.last_name,
    national_id: "",
    email: e.email ?? "",
    mobile: e.mobile ?? "",
    date_of_birth: e.date_of_birth ?? "",
    hire_date: e.hire_date,
    termination_date: e.termination_date ?? "",
    status: e.status,
    job_title: e.job_title ?? "",
    branch_id: e.branch_id ?? "",
    site_id: e.site_id ?? "",
    department_id: e.department_id ?? "",
    manager_id: e.manager_id ?? "",
    employee_type: e.employee_type,
    pay_basis: e.pay_basis,
    pay_frequency: e.pay_frequency,
    base_rate: e.base_rate ?? "",
    overtime_eligible: e.overtime_eligible,
    clocks: e.clocks,
    work_pattern_id: e.work_pattern_id ?? "",
    default_shift_id: e.default_shift_id ?? "",
    bank_name: e.bank_name ?? "",
    bank_account_number: "",
    bank_branch_code: e.bank_branch_code ?? "",
    account_type: e.account_type ?? "",
    tax_number: e.tax_number ?? "",
    medical_aid_dependants: e.medical_aid_dependants,
    retirement_fund_flags: e.retirement_fund_flags ?? "",
    uif_exempt: e.uif_exempt,
    notes: e.notes ?? "",
  };
}

function s(v: string): string | null {
  const t = v.trim();
  return t ? t : null;
}

function d(v: string): string | null {
  const t = v.trim();
  return t ? t : null;
}

function n(v: string): number | null {
  const t = v.trim();
  if (!t) return null;
  const x = Number(t);
  return Number.isFinite(x) ? x : null;
}

async function fetchWorkPatterns(): Promise<{ id: string; name: string }[]> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/work-patterns?limit=500"), {
      credentials: "include",
    }),
  );
  if (!res.ok) return [];
  const body = (await res.json().catch(() => ({}))) as {
    items?: { id: string; name: string }[];
  };
  return body.items ?? [];
}

async function fetchShifts(): Promise<{ id: string; name: string }[]> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/shifts?limit=500"), {
      credentials: "include",
    }),
  );
  if (!res.ok) return [];
  const body = (await res.json().catch(() => ({}))) as {
    items?: { id: string; name: string }[];
  };
  return body.items ?? [];
}

function buildCreateBody(f: FormState): EmployeeCreateIn {
  return {
    employee_code: f.employee_code.trim(),
    first_name: f.first_name.trim(),
    last_name: f.last_name.trim(),
    national_id: s(f.national_id),
    email: s(f.email),
    mobile: s(f.mobile),
    date_of_birth: d(f.date_of_birth),
    hire_date: f.hire_date,
    termination_date: d(f.termination_date),
    status: f.status,
    job_title: s(f.job_title),
    branch_id: s(f.branch_id),
    site_id: s(f.site_id),
    department_id: s(f.department_id),
    manager_id: s(f.manager_id),
    employee_type: f.employee_type,
    pay_basis: f.pay_basis,
    pay_frequency: f.pay_frequency,
    base_rate: n(f.base_rate),
    overtime_eligible: f.overtime_eligible,
    clocks: f.clocks,
    work_pattern_id: s(f.work_pattern_id),
    default_shift_id: s(f.default_shift_id),
    bank_name: s(f.bank_name),
    bank_account_number: s(f.bank_account_number),
    bank_branch_code: s(f.bank_branch_code),
    account_type: s(f.account_type),
    tax_number: s(f.tax_number),
    medical_aid_dependants: f.medical_aid_dependants,
    retirement_fund_flags: s(f.retirement_fund_flags),
    uif_exempt: f.uif_exempt,
    notes: s(f.notes),
  };
}

const PATCH_MUTABLE: (keyof EmployeeOut)[] = [
  "employee_code",
  "first_name",
  "last_name",
  "email",
  "mobile",
  "date_of_birth",
  "hire_date",
  "termination_date",
  "status",
  "job_title",
  "branch_id",
  "site_id",
  "department_id",
  "manager_id",
  "employee_type",
  "pay_basis",
  "pay_frequency",
  "overtime_eligible",
  "clocks",
  "work_pattern_id",
  "default_shift_id",
  "bank_name",
  "bank_branch_code",
  "account_type",
  "tax_number",
  "medical_aid_dependants",
  "retirement_fund_flags",
  "uif_exempt",
  "notes",
];

function buildPatchBody(initial: EmployeeOut, f: FormState): EmployeePatchIn {
  const body: Record<string, unknown> = { row_version: initial.row_version };
  const fAny = f as unknown as Record<string, unknown>;
  const iAny = initial as unknown as Record<string, unknown>;
  for (const key of PATCH_MUTABLE) {
    const keyStr = String(key);
    let next: unknown = fAny[keyStr];
    if (typeof next === "string") next = s(next) ?? (initial as any)[keyStr] === null ? next : next;
    // normalize empty strings to null for nullable fields
    const orig = iAny[keyStr] ?? null;
    const normalized = typeof next === "string" && !next.trim() ? null : next;
    if (normalized !== orig) body[keyStr] = normalized;
  }
  return body as EmployeePatchIn;
}

export interface EmployeeFormProps {
  opened: boolean;
  initial: EmployeeOut | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function EmployeeForm({
  opened,
  initial,
  onClose,
  onSuccess,
}: EmployeeFormProps) {
  const qc = useQueryClient();
  const isEdit = initial !== null;

  const [form, setForm] = useState<FormState>(BLANK);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!opened) return;
    setForm(initial ? fromEmployee(initial) : BLANK);
    setError(null);
    setFieldErrors({});
  }, [opened, initial]);

  const branches = useQuery({
    queryKey: ["refs", "branches"],
    queryFn: fetchBranches,
  });
  const sites = useQuery({
    queryKey: ["refs", "sites"],
    queryFn: fetchSites,
  });
  const departments = useQuery({
    queryKey: ["refs", "departments"],
    queryFn: fetchDepartments,
  });
  const managers = useQuery({
    queryKey: ["refs", "employees"],
    queryFn: fetchEmployees,
  });
  const workPatterns = useQuery({
    queryKey: ["refs", "work_patterns"],
    queryFn: fetchWorkPatterns,
  });
  const shifts = useQuery({
    queryKey: ["refs", "shifts"],
    queryFn: fetchShifts,
  });

  const branchOptions = useMemo(
    () =>
      (branches.data ?? []).map((b: { id: string; name: string }) => ({
        value: b.id,
        label: b.name,
      })),
    [branches.data],
  );
  const siteOptions = useMemo(
    () =>
      (sites.data ?? []).map((s: { id: string; name: string }) => ({
        value: s.id,
        label: s.name,
      })),
    [sites.data],
  );
  const departmentOptions = useMemo(
    () =>
      (departments.data ?? []).map((d: { id: string; name: string }) => ({
        value: d.id,
        label: d.name,
      })),
    [departments.data],
  );
  const managerOptions = useMemo(
    () =>
      (managers.data ?? []).map((m) => ({
        value: m.id,
        label: `${m.employee_code} — ${m.first_name} ${m.last_name}`.trim(),
      })),
    [managers.data],
  );
  const wpOptions = useMemo(
    () =>
      (workPatterns.data ?? []).map((w) => ({
        value: w.id,
        label: w.name,
      })),
    [workPatterns.data],
  );
  const shiftOptions = useMemo(
    () =>
      (shifts.data ?? []).map((sh) => ({
        value: sh.id,
        label: sh.name,
      })),
    [shifts.data],
  );

  const mutation = useMutation({
    mutationFn: async () => {
      if (isEdit && initial) {
        return patchEmployee(initial.id, buildPatchBody(initial, form));
      }
      return createEmployee(buildCreateBody(form));
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["employees"] });
      qc.invalidateQueries({ queryKey: ["refs", "employees"] });
      onSuccess();
      onClose();
    },
    onError: (err) => {
      const code =
        err instanceof EmployeesApiError
          ? err.code
          : err instanceof Error
            ? err.message
            : undefined;
      if (code === "duplicate_code") setError(strings.employees.errDupCode);
      else if (code === "record_changed")
        setError(strings.employees.errRecordChanged);
      else setError(code ? mapErrorCode(code) : strings.genericError);
    },
  });

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const submit = () => {
    setError(null);
    const fe: Record<string, string> = {};
    if (!form.employee_code.trim())
      fe.employee_code = strings.employees.errCodeRequired;
    if (!form.first_name.trim())
      fe.first_name = strings.employees.errFirstNameRequired;
    if (!form.last_name.trim())
      fe.last_name = strings.employees.errLastNameRequired;
    if (!form.hire_date) fe.hire_date = strings.employees.errHireRequired;
    if (Object.keys(fe).length) {
      setFieldErrors(fe);
      return;
    }
    setFieldErrors({});
    mutation.mutate();
  };

  return (
    <Modal
      opened={opened}
      onClose={() => {
        if (mutation.isPending) return;
        onClose();
      }}
      title={
        isEdit && initial
          ? strings.employees.formTitleEdit(
              `${initial.first_name} ${initial.last_name}`,
            )
          : strings.employees.formTitleCreate
      }
      size="xl"
    >
      <ScrollArea.Autosize mah="75vh">
        <Stack gap="sm">
          {error ? (
            <Alert color="red" data-testid="employee-form-error">
              {error}
            </Alert>
          ) : null}

          <Divider label={strings.employees.sectionBasic} labelPosition="left" />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              label={strings.employees.fCode}
              value={form.employee_code}
              onChange={(e) => set("employee_code", e.currentTarget.value)}
              error={fieldErrors.employee_code}
              required
              data-testid="emp-code"
            />
            <Select
              label={strings.employees.fStatus}
              data={STATUSES}
              value={form.status}
              onChange={(v) => v && set("status", v)}
              allowDeselect={false}
              data-testid="emp-status"
            />
            <TextInput
              label={strings.employees.fFirstName}
              value={form.first_name}
              onChange={(e) => set("first_name", e.currentTarget.value)}
              error={fieldErrors.first_name}
              required
              data-testid="emp-first-name"
            />
            <TextInput
              label={strings.employees.fLastName}
              value={form.last_name}
              onChange={(e) => set("last_name", e.currentTarget.value)}
              error={fieldErrors.last_name}
              required
              data-testid="emp-last-name"
            />
            <TextInput
              label={strings.employees.fJobTitle}
              value={form.job_title}
              onChange={(e) => set("job_title", e.currentTarget.value)}
              data-testid="emp-job-title"
            />
            <TextInput
              label={strings.employees.fHireDate}
              type="date"
              value={form.hire_date}
              onChange={(e) => set("hire_date", e.currentTarget.value)}
              error={fieldErrors.hire_date}
              required
              data-testid="emp-hire-date"
            />
            <TextInput
              label={strings.employees.fTerminationDate}
              type="date"
              value={form.termination_date}
              onChange={(e) =>
                set("termination_date", e.currentTarget.value)
              }
              data-testid="emp-termination-date"
            />
          </SimpleGrid>

          <Divider label={strings.employees.sectionContact} labelPosition="left" />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              label={strings.employees.fEmail}
              value={form.email}
              onChange={(e) => set("email", e.currentTarget.value)}
              data-testid="emp-email"
            />
            <TextInput
              label={strings.employees.fMobile}
              value={form.mobile}
              onChange={(e) => set("mobile", e.currentTarget.value)}
              data-testid="emp-mobile"
            />
            <TextInput
              label={strings.employees.fDob}
              type="date"
              value={form.date_of_birth}
              onChange={(e) => set("date_of_birth", e.currentTarget.value)}
              data-testid="emp-dob"
            />
            <TextInput
              label={strings.employees.fNationalId}
              value={form.national_id}
              onChange={(e) => set("national_id", e.currentTarget.value)}
              disabled={isEdit}
              description={isEdit ? strings.employees.readOnlyEdit : undefined}
              data-testid="emp-national-id"
            />
          </SimpleGrid>

          <Divider
            label={strings.employees.sectionAssignment}
            labelPosition="left"
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select
              label={strings.employees.fBranch}
              data={branchOptions}
              value={form.branch_id || null}
              onChange={(v) => set("branch_id", v ?? "")}
              clearable
              searchable
              data-testid="emp-branch"
            />
            <Select
              label={strings.employees.fSite}
              data={siteOptions}
              value={form.site_id || null}
              onChange={(v) => set("site_id", v ?? "")}
              clearable
              searchable
              description={
                isEdit && initial?.site_timezone
                  ? `${strings.employees.fSiteTimezone}: ${initial.site_timezone}`
                  : undefined
              }
              data-testid="emp-site"
            />
            <Select
              label={strings.employees.fDepartment}
              data={departmentOptions}
              value={form.department_id || null}
              onChange={(v) => set("department_id", v ?? "")}
              clearable
              searchable
              data-testid="emp-department"
            />
            <Select
              label={strings.employees.fManager}
              data={managerOptions}
              value={form.manager_id || null}
              onChange={(v) => set("manager_id", v ?? "")}
              clearable
              searchable
              data-testid="emp-manager"
            />
            <Select
              label={strings.employees.fWorkPattern}
              data={wpOptions}
              value={form.work_pattern_id || null}
              onChange={(v) => set("work_pattern_id", v ?? "")}
              clearable
              searchable
              data-testid="emp-work-pattern"
            />
            <Select
              label={strings.employees.fDefaultShift}
              data={shiftOptions}
              value={form.default_shift_id || null}
              onChange={(v) => set("default_shift_id", v ?? "")}
              clearable
              searchable
              data-testid="emp-default-shift"
            />
          </SimpleGrid>

          <Divider label={strings.employees.sectionPay} labelPosition="left" />
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <Select
              label={strings.employees.fEmployeeType}
              data={EMPLOYEE_TYPES.map((v) => ({ value: v, label: v }))}
              value={form.employee_type}
              onChange={(v) => v && set("employee_type", v)}
              allowDeselect={false}
              data-testid="emp-employee-type"
            />
            <Select
              label={strings.employees.fPayBasis}
              data={PAY_BASES.map((v) => ({ value: v, label: v }))}
              value={form.pay_basis}
              onChange={(v) => v && set("pay_basis", v)}
              allowDeselect={false}
              data-testid="emp-pay-basis"
            />
            <Select
              label={strings.employees.fPayFrequency}
              data={PAY_FREQUENCIES.map((v) => ({ value: v, label: v }))}
              value={form.pay_frequency}
              onChange={(v) => v && set("pay_frequency", v)}
              allowDeselect={false}
              data-testid="emp-pay-frequency"
            />
            <TextInput
              label={strings.employees.fBaseRate}
              value={form.base_rate}
              onChange={(e) => set("base_rate", e.currentTarget.value)}
              disabled={isEdit}
              description={isEdit ? strings.employees.readOnlyEdit : undefined}
              data-testid="emp-base-rate"
            />
            <Checkbox
              label={strings.employees.fOvertimeEligible}
              checked={form.overtime_eligible}
              onChange={(e) => set("overtime_eligible", e.currentTarget.checked)}
              data-testid="emp-overtime-eligible"
            />
            <Checkbox
              label={strings.employees.fClocks}
              checked={form.clocks}
              onChange={(e) => set("clocks", e.currentTarget.checked)}
              data-testid="emp-clocks"
            />
          </SimpleGrid>

          <Divider label={strings.employees.sectionBank} labelPosition="left" />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              label={strings.employees.fBankName}
              value={form.bank_name}
              onChange={(e) => set("bank_name", e.currentTarget.value)}
              data-testid="emp-bank-name"
            />
            <TextInput
              label={strings.employees.fBankAccount}
              value={form.bank_account_number}
              onChange={(e) =>
                set("bank_account_number", e.currentTarget.value)
              }
              disabled={isEdit}
              description={isEdit ? strings.employees.readOnlyEdit : undefined}
              data-testid="emp-bank-account"
            />
            <TextInput
              label={strings.employees.fBankBranch}
              value={form.bank_branch_code}
              onChange={(e) => set("bank_branch_code", e.currentTarget.value)}
              data-testid="emp-bank-branch"
            />
            <TextInput
              label={strings.employees.fAccountType}
              value={form.account_type}
              onChange={(e) => set("account_type", e.currentTarget.value)}
              data-testid="emp-account-type"
            />
            <TextInput
              label={strings.employees.fTaxNumber}
              value={form.tax_number}
              onChange={(e) => set("tax_number", e.currentTarget.value)}
              data-testid="emp-tax-number"
            />
            <Checkbox
              label={strings.employees.fUifExempt}
              checked={form.uif_exempt}
              onChange={(e) => set("uif_exempt", e.currentTarget.checked)}
              data-testid="emp-uif-exempt"
            />
          </SimpleGrid>

          <Divider label={strings.employees.sectionNotes} labelPosition="left" />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <NumberInput
              label={strings.employees.fMedicalAidDependants}
              value={form.medical_aid_dependants}
              onChange={(v) =>
                set(
                  "medical_aid_dependants",
                  typeof v === "number" ? v : 0,
                )
              }
              min={0}
              data-testid="emp-medical-dependants"
            />
            <TextInput
              label={strings.employees.fRetirementFundFlags}
              value={form.retirement_fund_flags}
              onChange={(e) =>
                set("retirement_fund_flags", e.currentTarget.value)
              }
              data-testid="emp-retirement-flags"
            />
          </SimpleGrid>
          <Textarea
            label={strings.employees.fNotes}
            value={form.notes}
            onChange={(e) => set("notes", e.currentTarget.value)}
            minRows={2}
            data-testid="emp-notes"
          />

          <Text size="xs" c="dimmed">
            &nbsp;
          </Text>

          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={onClose}
              disabled={mutation.isPending}
              data-testid="emp-cancel"
            >
              {strings.employees.cancelButton}
            </Button>
            <Button
              onClick={submit}
              loading={mutation.isPending}
              data-testid="emp-submit"
            >
              {strings.employees.saveButton}
            </Button>
          </Group>
        </Stack>
      </ScrollArea.Autosize>
    </Modal>
  );
}