import { useState } from "react";
import {
  useInfiniteQuery, useMutation, useQuery, useQueryClient,
} from "@tanstack/react-query";
import {
  Alert, Badge, Button, Group, Loader, Modal, Select, Stack, Table,
  Text, TextInput, Title,
} from "@mantine/core";
import {
  createStructure, deactivateStructure, listStructures,
  type ComponentKind, type PayBasis, type StructureComponentIn,
  type StructureCreateIn, type StructureOut,
} from "../api/salaryStructures";
import {
  fetchDeductionTypes, fetchEarningTypes,
  type DeductionTypeOut, type EarningTypeOut,
} from "../api/payrollTypes";

const PAGE_SIZE = 100;

type ComponentDraft = {
  key: string;
  kind: ComponentKind;
  earning_type_id: string | null;
  deduction_type_id: string | null;
  amount: string;
  rate: string;
};

type DraftState = {
  name: string;
  description: string;
  payBasis: PayBasis;
  baseRate: string;
  components: ComponentDraft[];
};

function _newKey(): string {
  return Math.random().toString(36).slice(2, 10);
}

function _emptyEarningDraft(): ComponentDraft {
  return {
    key: _newKey(), kind: "earning",
    earning_type_id: null, deduction_type_id: null,
    amount: "", rate: "",
  };
}

function _emptyDeductionDraft(): ComponentDraft {
  return {
    key: _newKey(), kind: "deduction",
    earning_type_id: null, deduction_type_id: null,
    amount: "", rate: "",
  };
}

function _emptyDraft(): DraftState {
  return {
    name: "", description: "", payBasis: "monthly",
    baseRate: "", components: [],
  };
}

function _draftToInput(d: DraftState): StructureCreateIn {
  return {
    name: d.name,
    description: d.description || null,
    pay_basis: d.payBasis,
    base_rate: d.baseRate,
    components: d.components.map<StructureComponentIn>((c) => ({
      kind: c.kind,
      earning_type_id: c.kind === "earning" ? c.earning_type_id : null,
      deduction_type_id: c.kind === "deduction" ? c.deduction_type_id : null,
      amount: c.amount || null,
      rate: c.rate || null,
    })),
  };
}

function mapStructureError(code: string): string {
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
    case "invalid_cursor":
      return "Pagination cursor is invalid. Reload the page.";
    default:
      return "Something went wrong. Please try again.";
  }
}

export function SalaryStructuresPage() {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [draft, setDraft] = useState<DraftState>(_emptyDraft);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyDeactivate, setBusyDeactivate] = useState<string | null>(null);

  const structures = useInfiniteQuery({
    queryKey: ["salary_structures"],
    queryFn: ({ pageParam }) =>
      listStructures({ limit: PAGE_SIZE, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
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

  const create = useMutation({
    mutationFn: createStructure,
    onSuccess: () => {
      setCreateOpen(false);
      setDraft(_emptyDraft());
      setDraftError(null);
      qc.invalidateQueries({ queryKey: ["salary_structures"] });
    },
    onError: (err) => {
      const code = err instanceof Error ? err.message : "unknown";
      setDraftError(mapStructureError(code));
    },
  });

  const deactivate = useMutation({
    mutationFn: deactivateStructure,
    onMutate: (gid: string) => { setBusyDeactivate(gid); setActionError(null); },
    onSettled: () => { setBusyDeactivate(null); },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["salary_structures"] });
    },
    onError: (err) => {
      const code = err instanceof Error ? err.message : "unknown";
      setActionError(mapStructureError(code));
    },
  });

  const earningOptions = (earningTypes.data?.items ?? [])
    .filter((et: EarningTypeOut) =>
      !et.is_system && et.code !== "BASE_MONTHLY" && et.is_active)
    .map((et) => ({ value: et.id, label: `${et.code} — ${et.name}` }));

  const deductionOptions = (deductionTypes.data?.items ?? [])
    .filter((dt: DeductionTypeOut) => !dt.is_system && dt.is_active)
    .map((dt) => ({ value: dt.id, label: `${dt.code} — ${dt.name}` }));

  const showTypesError = earningTypes.isError || deductionTypes.isError;

  const submitDraft = () => {
    setDraftError(null);
    if (!draft.name.trim()) {
      setDraftError("Name is required.");
      return;
    }
    if (!draft.baseRate) {
      setDraftError("Base rate is required.");
      return;
    }
    for (const c of draft.components) {
      if (c.kind === "earning") {
        if (!c.earning_type_id) {
          setDraftError("Each earning component needs a type.");
          return;
        }
        if ((!c.amount && !c.rate) || (c.amount && c.rate)) {
          setDraftError(
            "Each earning component needs exactly one of amount or rate.",
          );
          return;
        }
      } else {
        if (!c.deduction_type_id) {
          setDraftError("Each deduction component needs a type.");
          return;
        }
        if (!c.amount) {
          setDraftError("Each deduction component needs an amount.");
          return;
        }
      }
    }
    create.mutate(_draftToInput(draft));
  };

  const updateComponent = (i: number, patch: Partial<ComponentDraft>) => {
    const next = [...draft.components];
    next[i] = { ...next[i], ...patch };
    setDraft({ ...draft, components: next });
  };

  const items: StructureOut[] =
    structures.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <Stack gap="md" data-testid="salary-structures-page">
      <Group justify="space-between">
        <div>
          <Title order={2}>Salary structures</Title>
          <Text size="sm" c="dimmed">
            Versioned compensation templates. Editing a template creates a new version.
          </Text>
        </div>
        <Button
          data-testid="new-structure-button"
          onClick={() => {
            setDraft(_emptyDraft());
            setDraftError(null);
            setCreateOpen(true);
          }}
        >
          New structure
        </Button>
      </Group>

      {showTypesError && (
        <Alert color="red" data-testid="types-error">
          Could not load earning or deduction types.
        </Alert>
      )}
      {actionError && (
        <Alert color="red" data-testid="action-error" withCloseButton
          onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      {structures.isPending && (
        <Loader data-testid="structures-loading" />
      )}
      {structures.isError && (
        <Alert color="red" data-testid="structures-error">
          Could not load salary structures.
        </Alert>
      )}
      {structures.isSuccess && items.length === 0 && (
        <Text c="dimmed" data-testid="structures-empty">
          No salary structures yet.
        </Text>
      )}
      {structures.isSuccess && items.length > 0 && (
        <Table data-testid="structures-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Pay basis</Table.Th>
              <Table.Th>Base rate</Table.Th>
              <Table.Th>Version</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((s: StructureOut) => (
              <Table.Tr key={s.id} data-testid={`structure-row-${s.id}`}>
                <Table.Td>{s.name}</Table.Td>
                <Table.Td>{s.pay_basis}</Table.Td>
                <Table.Td>{s.base_rate}</Table.Td>
                <Table.Td>{s.version_number}</Table.Td>
                <Table.Td>
                  {s.is_active ? (
                    <Badge color="green">Active</Badge>
                  ) : (
                    <Badge color="red">Inactive</Badge>
                  )}
                </Table.Td>
                <Table.Td>
                  <Group gap="xs">
                    <Button size="xs" variant="default"
                      data-testid={`structure-open-${s.id}`}
                      component="a"
                      href={`/payroll/salary-structures/${s.structure_group_id}`}>
                      Open
                    </Button>
                    <Button size="xs" variant="default" color="red"
                      data-testid={`structure-deactivate-${s.id}`}
                      loading={busyDeactivate === s.structure_group_id}
                      disabled={!s.is_active}
                      onClick={() => {
                        if (!window.confirm(
                          "Deactivate this salary structure? Existing assignments " +
                          "keep working but no new ones can be created.",
                        )) return;
                        deactivate.mutate(s.structure_group_id);
                      }}>
                      Deactivate
                    </Button>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      {structures.isFetchNextPageError && (
        <Alert color="red" data-testid="structures-load-more-error">
          Could not load more salary structures.
        </Alert>
      )}
      {structures.hasNextPage && (
        <Group justify="center">
          <Button
            variant="default"
            data-testid="structures-load-more"
            loading={structures.isFetchingNextPage}
            onClick={() => structures.fetchNextPage()}
          >
            Load more
          </Button>
        </Group>
      )}

      <Modal
        opened={createOpen}
        onClose={() => setCreateOpen(false)}
        title="New salary structure"
        size="xl"
      >
        <Stack gap="sm">
          <TextInput
            label="Name"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.currentTarget.value })}
            data-testid="field-name"
          />
          <TextInput
            label="Description"
            value={draft.description}
            onChange={(e) =>
              setDraft({ ...draft, description: e.currentTarget.value })}
            data-testid="field-description"
          />
          <Select
            label="Pay basis"
            data={[
              { value: "hourly", label: "hourly" },
              { value: "daily", label: "daily" },
              { value: "monthly", label: "monthly" },
            ]}
            value={draft.payBasis}
            onChange={(v) =>
              setDraft({ ...draft, payBasis: (v as PayBasis) ?? "monthly" })}
            data-testid="field-pay-basis"
          />
          <TextInput
            label="Base rate"
            value={draft.baseRate}
            onChange={(e) =>
              setDraft({ ...draft, baseRate: e.currentTarget.value })}
            data-testid="field-base-rate"
          />

          <Text fw={500}>Components</Text>
          {draft.components.map((c, i) => (
            <Group key={c.key} data-testid={`component-row-${i}`} align="end">
              {c.kind === "earning" ? (
                <Select
                  label="Type"
                  data={earningOptions}
                  value={c.earning_type_id}
                  onChange={(v) => updateComponent(i, { earning_type_id: v })}
                  searchable
                  data-testid={`component-type-${i}`}
                  style={{ minWidth: 220 }}
                />
              ) : (
                <Select
                  label="Type"
                  data={deductionOptions}
                  value={c.deduction_type_id}
                  onChange={(v) => updateComponent(i, { deduction_type_id: v })}
                  searchable
                  data-testid={`component-type-${i}`}
                  style={{ minWidth: 220 }}
                />
              )}
              <TextInput
                label="Amount"
                value={c.amount}
                onChange={(e) =>
                  updateComponent(i, { amount: e.currentTarget.value })}
                data-testid={`component-amount-${i}`}
                style={{ width: 120 }}
              />
              {c.kind === "earning" && (
                <TextInput
                  label="Rate"
                  value={c.rate}
                  onChange={(e) =>
                    updateComponent(i, { rate: e.currentTarget.value })}
                  data-testid={`component-rate-${i}`}
                  style={{ width: 120 }}
                />
              )}
              <Button variant="default" color="red" size="xs"
                data-testid={`component-remove-${i}`}
                onClick={() => {
                  setDraft({
                    ...draft,
                    components: draft.components.filter((_, j) => j !== i),
                  });
                }}>
                Remove
              </Button>
            </Group>
          ))}
          <Group>
            <Button variant="default" size="xs"
              data-testid="add-earning"
              onClick={() =>
                setDraft({
                  ...draft,
                  components: [...draft.components, _emptyEarningDraft()],
                })}>
              Add earning
            </Button>
            <Button variant="default" size="xs"
              data-testid="add-deduction"
              onClick={() =>
                setDraft({
                  ...draft,
                  components: [...draft.components, _emptyDeductionDraft()],
                })}>
              Add deduction
            </Button>
          </Group>

          {draftError && (
            <Alert color="red" data-testid="draft-error">{draftError}</Alert>
          )}

          <Group justify="flex-end">
            <Button variant="default" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button loading={create.isPending} onClick={submitDraft}
              data-testid="create-submit">
              Save
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}