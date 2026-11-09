import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Badge, Button, Group, Loader, Modal, Stack, Table,
  Text, TextInput, Title,
} from "@mantine/core";
import {
  deactivateStructure, editStructure, getCurrentStructure,
  listVersions, type StructureOut,
} from "../api/salaryStructures";

function mapError(code: string): string {
  switch (code) {
    case "record_changed":
      return "This structure was changed by another user. Reload and try again.";
    case "structure_inactive":
      return "This structure is inactive.";
    default:
      return "Something went wrong. Please try again.";
  }
}

export function SalaryStructureDetailPage() {
  const { groupId } = useParams<{ groupId: string }>();
  const qc = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editBaseRate, setEditBaseRate] = useState("");
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

  const save = useMutation({
    mutationFn: (body: {
      version_number: number; row_version: number;
      name: string; description: string | null; base_rate: string;
    }) => editStructure(groupId!, body),
    onSuccess: () => {
      setEditOpen(false);
      setEditError(null);
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

  const openEdit = () => {
    setEditName(s.name);
    setEditDesc(s.description ?? "");
    setEditBaseRate(s.base_rate);
    setEditError(null);
    setEditOpen(true);
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
        onClose={() => setEditOpen(false)}
        title="Edit salary structure (creates new version)"
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
          {editError && (
            <Alert color="red" data-testid="edit-error">{editError}</Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setEditOpen(false)}>
              Cancel
            </Button>
            <Button
              data-testid="edit-submit"
              loading={save.isPending}
              onClick={() => {
                setEditError(null);
                if (!editName.trim()) {
                  setEditError("Name is required.");
                  return;
                }
                if (!editBaseRate) {
                  setEditError("Base rate is required.");
                  return;
                }
                save.mutate({
                  version_number: s.version_number,
                  row_version: s.row_version,
                  name: editName,
                  description: editDesc || null,
                  base_rate: editBaseRate,
                });
              }}
            >
              Save
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}