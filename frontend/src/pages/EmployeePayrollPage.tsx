import { useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Badge, Button, Group, Loader, Stack, Table, Text,
  TextInput, Title,
} from "@mantine/core";
import {
  checkCollisions, fetchEmployeeAssignments, submitAssignment,
  type AssignmentOut, type CheckCollisionsOut, type ManualOverlapOut,
  type OverrideManualIdIn,
} from "../api/salaryAssignments";
import { listStructures } from "../api/salaryStructures";
import { fetchEmployees } from "../api/employees";

function statusColor(s: string): string {
  switch (s) {
    case "approved": return "green";
    case "rejected": return "red";
    case "cancelled": return "gray";
    default: return "blue";
  }
}

function mapAssignmentError(code: string): string {
  switch (code) {
    case "backdating_not_permitted":
      return "Effective date must be later than today.";
    case "no_pay_periods_configured":
      return "No pay periods configured. Create a pay-period calendar first.";
    case "effective_date_affects_open_period":
      return "Effective date affects an open pay period. Close it first.";
    case "effective_date_not_period_boundary":
      return "Effective date must align with a pay-period boundary.";
    case "pay_basis_mismatch":
      return "Employee pay basis does not match the structure's pay basis.";
    case "structure_inactive":
      return "This structure is inactive.";
    case "structure_not_current":
      return "Only the current version of a structure can be assigned.";
    case "pending_salary_structure_assignment_exists":
      return "An assignment for this employee is already pending.";
    case "pending_individual_change_requests_block_assignment":
      return "Resolve pending individual change requests first.";
    case "manual_component_type_collision":
      return "Unselected manual components overlap this date.";
    case "manual_component_same_start_date":
      return "A manual component starts on the same day as this assignment.";
    case "invalid_override_manual_id":
      return "One or more selected overrides are not valid.";
    default:
      return "Something went wrong. Please try again.";
  }
}

// ---------------------------- Index view ----------------------------

function EmployeePayrollIndex() {
  const employees = useQuery({
    queryKey: ["refs", "employees"],
    queryFn: () => fetchEmployees(),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <Stack gap="md" data-testid="employee-payroll-index">
      <Title order={2}>Employee payroll</Title>
      <Text size="sm" c="dimmed">
        Select an employee to view salary assignments and submit a new structure.
      </Text>
      {employees.isLoading && <Loader data-testid="employees-loading" />}
      {employees.isError && (
        <Alert color="red" data-testid="employees-error">
          Could not load employees.
        </Alert>
      )}
      {employees.isSuccess && (
        <Table data-testid="employees-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Code</Table.Th>
              <Table.Th>Name</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(employees.data ?? []).map((e) => (
              <Table.Tr key={e.id} data-testid={`employee-row-${e.id}`}>
                <Table.Td>{e.employee_code}</Table.Td>
                <Table.Td>
                  {e.first_name} {e.last_name}
                </Table.Td>
                <Table.Td>
                  <Button
                    size="xs"
                    variant="default"
                    component={Link}
                    to={`/payroll/employee-payroll/${e.id}`}
                    data-testid={`employee-open-${e.id}`}
                  >
                    Open payroll
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

// ---------------------------- Detail view ----------------------------

function EmployeePayrollDetail({ employeeId }: { employeeId: string }) {
  const qc = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [structureId, setStructureId] = useState<string>("");
  const [effectiveFrom, setEffectiveFrom] = useState<string>("");
  const [collisions, setCollisions] = useState<CheckCollisionsOut | null>(null);
  const [selectedOverrides, setSelectedOverrides] = useState<Set<string>>(new Set());
  const [formError, setFormError] = useState<string | null>(null);

  const assignments = useQuery({
    queryKey: ["employee_assignments", employeeId],
    queryFn: () => fetchEmployeeAssignments(employeeId),
  });
  const structures = useQuery({
    queryKey: ["salary_structures"],
    queryFn: listStructures,
  });
  const employees = useQuery({
    queryKey: ["refs", "employees"],
    queryFn: () => fetchEmployees(),
    staleTime: 5 * 60 * 1000,
  });

  const employee = useMemo(() => {
    const list = employees.data ?? [];
    return list.find((e) => e.id === employeeId) ?? null;
  }, [employees.data, employeeId]);

  const submit = useMutation({
    mutationFn: submitAssignment,
    onSuccess: () => {
      setFormOpen(false);
      setStructureId("");
      setEffectiveFrom("");
      setCollisions(null);
      setSelectedOverrides(new Set());
      setFormError(null);
      qc.invalidateQueries({ queryKey: ["employee_assignments", employeeId] });
    },
    onError: (err) => {
      const code = err instanceof Error ? err.message : "unknown";
      setFormError(mapAssignmentError(code));
    },
  });

  const check = useMutation({
    mutationFn: checkCollisions,
    onSuccess: (data) => {
      setCollisions(data);
      setFormError(null);
    },
    onError: (err) => {
      const code = err instanceof Error ? err.message : "unknown";
      setFormError(mapAssignmentError(code));
    },
  });

  const toggleOverride = (key: string) => {
    setSelectedOverrides((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const overrideIds: OverrideManualIdIn[] = Array.from(selectedOverrides).map(
    (key) => {
      const [kind, id] = key.split("|");
      return {
        kind: kind as OverrideManualIdIn["kind"],
        id,
      };
    },
  );

  const resetForm = () => {
    setStructureId("");
    setEffectiveFrom("");
    setCollisions(null);
    setSelectedOverrides(new Set());
    setFormError(null);
  };

  return (
    <Stack gap="md" data-testid="employee-payroll-detail-page">
      <Text size="sm" c="dimmed">
        <Link to="/payroll/employee-payroll" data-testid="back-link">
          ← Back to employee payroll
        </Link>
      </Text>
      <Group justify="space-between">
        <div>
          <Title order={2} data-testid="employee-name">
            {employee
              ? `${employee.first_name} ${employee.last_name}`
              : `Employee ${employeeId.slice(0, 8)}…`}
          </Title>
          {employee && (
            <Text size="sm" c="dimmed" data-testid="employee-code">
              {employee.employee_code}
            </Text>
          )}
        </div>
        <Button
          data-testid="new-assignment-button"
          onClick={() => {
            resetForm();
            setFormOpen(true);
          }}
        >
          New assignment
        </Button>
      </Group>

      {assignments.isLoading && <Loader data-testid="assignments-loading" />}
      {assignments.isError && (
        <Alert color="red" data-testid="assignments-error">
          Could not load assignments.
        </Alert>
      )}
      {assignments.isSuccess && assignments.data.items.length === 0 && (
        <Text c="dimmed" data-testid="assignments-empty">
          No assignments yet.
        </Text>
      )}
      {assignments.isSuccess && assignments.data.items.length > 0 && (
        <Table data-testid="assignments-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Effective from</Table.Th>
              <Table.Th>Effective to</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Submitted</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {assignments.data.items.map((a: AssignmentOut) => (
              <Table.Tr key={a.id} data-testid={`assignment-row-${a.id}`}>
                <Table.Td>{a.effective_from}</Table.Td>
                <Table.Td>{a.effective_to ?? "—"}</Table.Td>
                <Table.Td>
                  <Badge color={statusColor(a.status)}>{a.status}</Badge>
                </Table.Td>
                <Table.Td>{a.submitted_at}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      {formOpen && (
        <Stack gap="sm" data-testid="assignment-form">
          <Title order={4}>New salary assignment</Title>
          <select
            data-testid="form-structure"
            value={structureId}
            onChange={(e) => setStructureId(e.target.value)}
            style={{ padding: 6 }}
          >
            <option value="">— choose structure —</option>
            {(structures.data?.items ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} (v{s.version_number}, {s.pay_basis}, {s.base_rate})
              </option>
            ))}
          </select>
          <TextInput
            type="date"
            label="Effective from"
            data-testid="form-effective-from"
            value={effectiveFrom}
            onChange={(e) => setEffectiveFrom(e.currentTarget.value)}
          />

          {structureId && effectiveFrom && (
            <Button
              variant="default"
              data-testid="check-collisions-button"
              loading={check.isPending}
              onClick={() => {
                setFormError(null);
                setCollisions(null);
                setSelectedOverrides(new Set());
                check.mutate({
                  employee_id: employeeId,
                  structure_id: structureId,
                  effective_from: effectiveFrom,
                  override_manual_ids: [],
                });
              }}
            >
              Check overlaps
            </Button>
          )}

          {collisions && collisions.manual.length === 0 &&
            collisions.structure_owned.length === 0 && (
              <Alert color="green" data-testid="no-collisions">
                No overlapping manual components.
              </Alert>
            )}

          {collisions && collisions.manual.length > 0 && (
            <Stack gap="xs" data-testid="manual-overlaps">
              <Text fw={500}>Manual components</Text>
              {collisions.manual.map((m: ManualOverlapOut) => {
                const key = `${m.kind}|${m.id}`;
                const eligible = m.status === "requires_override";
                return (
                  <label
                    key={key}
                    data-testid={`manual-overlap-${m.id}`}
                    style={{ display: "flex", gap: 8, alignItems: "center" }}
                  >
                    <input
                      type="checkbox"
                      disabled={!eligible}
                      checked={selectedOverrides.has(key)}
                      onChange={() => toggleOverride(key)}
                      data-testid={`override-checkbox-${m.id}`}
                    />
                    <span>
                      {m.kind} · {m.component_kind} · {m.effective_from} ·{" "}
                      <em>{m.status}</em>
                    </span>
                  </label>
                );
              })}
            </Stack>
          )}

          {collisions && collisions.structure_owned.length > 0 && (
            <Alert color="blue" data-testid="structure-owned-overlaps">
              {collisions.structure_owned.length} prior structure-owned
              component(s) will be closed automatically.
            </Alert>
          )}

          {formError && (
            <Alert color="red" data-testid="form-error">{formError}</Alert>
          )}

          <Group justify="flex-end">
            <Button variant="default" onClick={() => setFormOpen(false)}>
              Cancel
            </Button>
            <Button
              data-testid="submit-assignment-button"
              loading={submit.isPending}
              onClick={() => {
                setFormError(null);
                if (!structureId) {
                  setFormError("Choose a structure.");
                  return;
                }
                if (!effectiveFrom) {
                  setFormError("Effective date is required.");
                  return;
                }
                submit.mutate({
                  employee_id: employeeId,
                  structure_id: structureId,
                  effective_from: effectiveFrom,
                  override_manual_ids: overrideIds,
                });
              }}
            >
              Submit for approval
            </Button>
          </Group>
        </Stack>
      )}
    </Stack>
  );
}

// ---------------------------- Entry ----------------------------

export function EmployeePayrollPage() {
  const { employeeId } = useParams<{ employeeId?: string }>();
  if (!employeeId) return <EmployeePayrollIndex />;
  return <EmployeePayrollDetail employeeId={employeeId} />;
}