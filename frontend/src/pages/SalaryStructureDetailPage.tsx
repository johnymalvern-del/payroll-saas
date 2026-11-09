import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Badge, Button, Group, Loader, Modal, Select, Stack, Table,
  Text, TextInput, Title,
} from "@mantine/core";
import {
  deactivateStructure, editStructure, getCurrentStructure,
  listVersions,
  type ComponentKind, type StructureComponentIn, type StructureOut,
} from "../api/salaryStructures";
import {
  fetchDeductionTypes, fetchEarningTypes,
  type DeductionTypeOut, type EarningTypeOut,
} from "../api/payrollTypes";

function mapError(code: string): string {
  switch (code) {
    case "record_changed":
      return "This structure was changed by another user. Reload and try again.";
    case "structure_inactive":
      return "This structure is inactive.";
    case "system_earning_type_not_allowed_in_structure":
      return "System earning types cannot be used in salary structures.";
    case "base_monthly_component_not_allowed":
      return "BASE_MONTHLY cannot be a component; use the structure base rate.";
    case "inactive_earning_type_not_allowed":
      return "Inactive earning types cannot be used.";
    case "system_deduction_not_allowed_in_structure":
      return "System deduction types cannot be used.";
    case "inactive_deduction_type_not_allowed":
      return "Inactive deduction types cannot be used.";
    case "invalid_component":
      return "One or more components are invalid.";
    default:
      return "Something went wrong. Please try again.";
  }
}

type ComponentDraft = {
  key: string;
  id: string | null;
  kind: ComponentKind;
  earning_type_id: string | null;
  deduction_type_id: string | null;
  amount: string;
  rate: string;
};

function _newKey(): string {
  return Math.random().toString(36).slice(2, 10);
}

function _draftFromComponents(
  comps: StructureOut["components"],
): ComponentDraft[] {
  return comps.map((c) => ({
    key: _newKey(),
    id: c.id,
    kind: c.kind === "deduction" ? "deduction" : "earning",
    earning_type_id: c.earning_type_id,
    deduction_type_id: c.deduction_type_id,
    amount: c.amount ?? "",
    rate: c.rate ?? "",
  }));
}

function _emptyEarningDraft(): ComponentDraft {
  return {
    key: _newKey(), id: null, kind: "earning",
    earning_type_id: null, deduction_type_id: null,
    amount: "", rate: "",
  };
}

function _emptyDeductionDraft(): ComponentDraft {
  return {
    key: _newKey(), id: null, kind: "deduction",
    earning_type_id: null, deduction_type_id: null,
    amount: "", rate: "",
  };
}

function _draftToInput(d: ComponentDraft): StructureComponentIn {
  return {
    kind: d.kind,
    earning_type_id: d.kind === "earning" ? d.earning_type_id : null,
    deduction_type_id: d.kind === "deduction" ? d.deduction_type_id : null,
    amount: d.amount || null,
    rate: d.rate || null,
  };
}

function _validateComponents(components: ComponentDraft[]): string | null {
  for (const c of components) {
    if (c.kind === "earning") {
      if (!c.earning_type_id) {
        return "Each earning component needs a type.";
      }
      if ((!c.amount && !c.rate) || (c.amount && c.rate)) {
        return "Each earning component needs exactly one of amount or rate.";
      }
    } else {
      if (!c.deduction_type_id) {
        return "Each deduction component needs a type.";
      }
      if (!c.amount) {
        return "Each deduction component needs an amount.";
      }
    }
  }
  return null;
}

export function SalaryStructureDetailPage() {
  const { groupId } = useParams<{ groupId: string }>();
  const qc = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editBaseRate, setEditBaseRate] = useState("");
  const [editComponents, setEditComponents] = useState<ComponentDraft[]>([]);
  const [componentsDirty, setComponentsDirty] = useState(false);
  const [componentsExpanded, setComponentsExpanded] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const structure = useQuery({
    queryKey: ["salary_structure", groupId],
    queryFn: () => getCurrentStructure(groupId!),
    enabled: !!groupId,
  });
  const versions = useQuery({
    queryKey: ["salary_structure_versions", groupId],
    queryFn: () => listVersions(groupId!),
    enabled: !!groupId,
  });
  const earningTypes = useQuery({
    queryKey: ["payroll_earning_types"],
    queryFn: fetchEarningTypes,
    staleTime: 5 * 60 * 1000,
  });
  const deductionTypes = useQuery({
    queryKey: ["payroll_deduction_types"],
    queryFn: fetchDeductionTypes,
    staleTime: 5 * 60 * 1000,
  });

  const save = useMutation({
    mutationFn: (body: {
      version_number: number; row_version: number;
      name: string; description: string | null; base_rate: string;
      components?: StructureComponentIn[];
    }) => editStructure(groupId!, body),
    onSuccess: () => {
      setEditOpen(false);
      setEditError(null);
      setComponentsDirty(false);
      setComponentsExpanded(false);
      qc.invalidateQueries({ queryKey: ["salary_structure", groupId] });
      qc.invalidateQueries({ queryKey: ["salary_structure_versions", groupId] });
      qc.invalidateQueries({ queryKey: ["salary_structures"] });
    },
    onError: (err) => {
      const code = err instanceof Error ? err.message : "unknown";
      setEditError(mapError(code));
    },
  });

  const deactivate = useMutation({
    mutationFn: () => deactivateStructure(groupId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["salary_structure", groupId] });
      qc.invalidateQueries({ queryKey: ["salary_structures"] });
    },
    onError: (err) => {
      const code = err instanceof Error ? err.message : "unknown";
      setActionError(mapError(code));
    },
  });

  if (!groupId) {
    return (
      <Alert color="red" data-testid="missing-group-id">
        Missing structure group id.
      </Alert>
    );
  }
  if (structure.isLoading) {
    return <Loader data-testid="structure-loading" />;
  }
  if (structure.isError || !structure.data) {
    return (
      <Alert color="red" data-testid="structure-error">
        Could not load the salary structure.
      </Alert>
    );
  }
  const s: StructureOut = structure.data;

  const earningOptions = (earningTypes.data?.items ?? [])
    .filter((et: EarningTypeOut) =>
      !et.is_system && et.code !== "BASE_MONTHLY" && et.is_active)
    .map((et) => ({ value: et.id, label: `${et.code} — ${et.name}` }));
  const deductionOptions = (deductionTypes.data?.items ?? [])
    .filter((dt: DeductionTypeOut) => !dt.is_system && dt.is_active)
    .map((dt) => ({ value: dt.id, label: `${dt.code} — ${dt.name}` }));

  const openEdit = () => {
    setEditName(s.name);
    setEditDesc(s.description ?? "");
    setEditBaseRate(s.base_rate);
    setEditComponents(_draftFromComponents(s.components));
    setComponentsDirty(false);
    setComponentsExpanded(false);
    setEditError(null);
    setEditOpen(true);
  };

  const closeEdit = () => {
    if (save.isPending) return;
    setEditOpen(false);
    setEditError(null);
    setComponentsDirty(false);
    setComponentsExpanded(false);
  };

  const markDirty = () => { if (!componentsDirty) setComponentsDirty(true); };

  const updateComponent = (i: number, patch: Partial<ComponentDraft>) => {
    const next = [...editComponents];
    next[i] = { ...next[i], ...patch };
    setEditComponents(next);
    markDirty();
  };

  const addEarning = () => {
    setEditComponents([...editComponents, _emptyEarningDraft()]);
    markDirty();
  };
  const addDeduction = () => {
    setEditComponents([...editComponents, _emptyDeductionDraft()]);
    markDirty();
  };
  const removeComponent = (i: number) => {
    setEditComponents(editComponents.filter((_, j) => j !== i));
    markDirty();
  };

  const submitEdit = () => {
    setEditError(null);
    if (!editName.trim()) {
      setEditError("Name is required.");
      return;
    }
    if (!editBaseRate) {
      setEditError("Base rate is required.");
      return;
    }
    if (componentsDirty) {
      const v = _validateComponents(editComponents);
      if (v) { setEditError(v); return; }
    }
    const body: Parameters<typeof save.mutate>[0] = {
      version_number: s.version_number,
      row_version: s.row_version,
      name: editName,
      description: editDesc || null,
      base_rate: editBaseRate,
    };
    if (componentsDirty) {
      body.components = editComponents.map(_draftToInput);
    }
    save.mutate(body);
  };

  return (
    <Stack gap="md" data-testid="salary-structure-detail-page">
      <Group justify="space-between">
        <div>
          <Text size="sm" c="dimmed">
            <Link to="/payroll/salary-structures" data-testid="back-link">
              ← Back to structures
            </Link>
          </Text>
          <Title order={2} data-testid="structure-name">{s.name}</Title>
          <Group gap="xs" mt={4}>
            <Badge data-testid="version-badge">
              Version {s.version_number}
            </Badge>
            {s.is_current && <Badge color="blue">Current</Badge>}
            {s.is_active ? (
              <Badge color="green">Active</Badge>
            ) : (
              <Badge color="red">Inactive</Badge>
            )}
          </Group>
        </div>
        <Group>
          <Button
            variant="default"
            data-testid="edit-button"
            onClick={openEdit}
            disabled={!s.is_active}
          >
            Edit
          </Button>
          <Button
            color="red"
            variant="default"
            data-testid="deactivate-button"
            disabled={!s.is_active}
            loading={deactivate.isPending}
            onClick={() => {
              if (!window.confirm(
                "Deactivate this salary structure group? Existing assignments " +
                "keep working but no new ones can be created.",
              )) return;
              deactivate.mutate();
            }}
          >
            Deactivate
          </Button>
        </Group>
      </Group>

      {actionError && (
        <Alert color="red" data-testid="action-error" withCloseButton
          onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      <Group>
        <Text><b>Pay basis:</b> {s.pay_basis}</Text>
        <Text><b>Base rate:</b> {s.base_rate}</Text>
      </Group>
      {s.description && (
        <Text size="sm" c="dimmed">{s.description}</Text>
      )}

      <Title order={4}>Components</Title>
      {s.components.length === 0 ? (
        <Text c="dimmed" data-testid="no-components">
          No components.
        </Text>
      ) : (
        <Table data-testid="components-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Kind</Table.Th>
              <Table.Th>Type ID</Table.Th>
              <Table.Th>Amount</Table.Th>
              <Table.Th>Rate</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {s.components.map((c) => (
              <Table.Tr key={c.id} data-testid={`component-${c.id}`}>
                <Table.Td>{c.kind}</Table.Td>
                <Table.Td>
                  {c.earning_type_id ?? c.deduction_type_id ?? "—"}
                </Table.Td>
                <Table.Td>{c.amount ?? "—"}</Table.Td>
                <Table.Td>{c.rate ?? "—"}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Title order={4}>Version history</Title>
      <Text size="sm" c="dimmed">
        Historical versions are immutable. Edits create a new version.
      </Text>
      {versions.isLoading && <Loader data-testid="versions-loading" />}
      {versions.isError && (
        <Alert color="red" data-testid="versions-error">
          Could not load versions.
        </Alert>
      )}
      {versions.isSuccess && (
        <Table data-testid="versions-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Version</Table.Th>
              <Table.Th>Name</Table.Th>
              <Table.Th>Base rate</Table.Th>
              <Table.Th>Current</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {versions.data.items.map((v) => (
              <Table.Tr key={v.id} data-testid={`version-row-${v.version_number}`}>
                <Table.Td>{v.version_number}</Table.Td>
                <Table.Td>{v.name}</Table.Td>
                <Table.Td>{v.base_rate}</Table.Td>
                <Table.Td>{v.is_current ? "Yes" : "No"}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Modal
        opened={editOpen}
        onClose={closeEdit}
        title="Edit salary structure (creates new version)"
        size="xl"
      >
        <Stack gap="sm">
          <TextInput
            label="Name"
            value={editName}
            onChange={(e) => setEditName(e.currentTarget.value)}
            data-testid="edit-name"
          />
          <TextInput
            label="Description"
            value={editDesc}
            onChange={(e) => setEditDesc(e.currentTarget.value)}
            data-testid="edit-description"
          />
          <TextInput
            label="Base rate"
            value={editBaseRate}
            onChange={(e) => setEditBaseRate(e.currentTarget.value)}
            data-testid="edit-base-rate"
          />

          <Group justify="space-between" align="center" mt="sm">
            <Text fw={500}>
              Components ({editComponents.length})
            </Text>
            <Button
              size="xs"
              variant="default"
              data-testid="toggle-components"
              onClick={() => setComponentsExpanded((v) => !v)}
            >
              {componentsExpanded ? "Hide components" : "Modify components"}
            </Button>
          </Group>
          <Text size="xs" c="dimmed">
            Editing components creates a new immutable version. Historical
            versions are never modified.
          </Text>

          {componentsExpanded && (
            <Stack gap="xs" data-testid="edit-components-editor">
              {editComponents.map((c, i) => (
                <Group key={c.key} data-testid={`edit-component-row-${i}`} align="end">
                  {c.kind === "earning" ? (
                    <Select
                      label="Type"
                      data={earningOptions}
                      value={c.earning_type_id}
                      onChange={(v) =>
                        updateComponent(i, { earning_type_id: v })}
                      searchable
                      data-testid={`edit-component-type-${i}`}
                      style={{ minWidth: 220 }}
                    />
                  ) : (
                    <Select
                      label="Type"
                      data={deductionOptions}
                      value={c.deduction_type_id}
                      onChange={(v) =>
                        updateComponent(i, { deduction_type_id: v })}
                      searchable
                      data-testid={`edit-component-type-${i}`}
                      style={{ minWidth: 220 }}
                    />
                  )}
                  <TextInput
                    label="Amount"
                    value={c.amount}
                    onChange={(e) =>
                      updateComponent(i, { amount: e.currentTarget.value })}
                    data-testid={`edit-component-amount-${i}`}
                    style={{ width: 120 }}
                  />
                  {c.kind === "earning" && (
                    <TextInput
                      label="Rate"
                      value={c.rate}
                      onChange={(e) =>
                        updateComponent(i, { rate: e.currentTarget.value })}
                      data-testid={`edit-component-rate-${i}`}
                      style={{ width: 120 }}
                    />
                  )}
                  <Button variant="default" color="red" size="xs"
                    data-testid={`edit-component-remove-${i}`}
                    onClick={() => removeComponent(i)}>
                    Remove
                  </Button>
                </Group>
              ))}
              <Group>
                <Button variant="default" size="xs"
                  data-testid="edit-add-earning"
                  onClick={addEarning}>
                  Add earning
                </Button>
                <Button variant="default" size="xs"
                  data-testid="edit-add-deduction"
                  onClick={addDeduction}>
                  Add deduction
                </Button>
              </Group>
            </Stack>
          )}

          {editError && (
            <Alert color="red" data-testid="edit-error">{editError}</Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={closeEdit}
              disabled={save.isPending}>
              Cancel
            </Button>
            <Button
              data-testid="edit-submit"
              loading={save.isPending}
              onClick={submitEdit}
            >
              Save
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}