import { useState } from "react";
import { Alert, Button, Group, Loader, Modal, Stack, Table, TextInput, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { branchesApi, type Branch } from "../../api/branches";
import { colors } from "../../theme/colors";

export function BranchesPage() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", code: "", address: "" });

  const list = useQuery({ queryKey: ["branches"], queryFn: branchesApi.list });
  const createM = useMutation({
    mutationFn: branchesApi.create,
    onSuccess: () => { setOpen(false); setForm({ name: "", code: "", address: "" }); qc.invalidateQueries({ queryKey: ["branches"] }); },
    onError: (e: Error) => setErr(e.message),
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Branches</Title>
        <Button onClick={() => { setErr(null); setOpen(true); }} data-testid="branches-add">Add branch</Button>
      </Group>
      {err && <Alert color={colors.problem} data-testid="branches-error">{err}</Alert>}
      {list.isLoading ? <Loader /> : list.isError ? (
        <Alert color={colors.problem}>Could not load branches.</Alert>
      ) : (
        <Table data-testid="branches-table">
          <Table.Thead><Table.Tr><Table.Th>Code</Table.Th><Table.Th>Name</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {(list.data?.items ?? []).map((b: Branch) => (
              <Table.Tr key={b.id}><Table.Td>{b.code}</Table.Td><Table.Td>{b.name}</Table.Td></Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <Modal opened={open} onClose={() => setOpen(false)} title="New branch">
        <Stack>
          <TextInput label="Name" value={form.name} onChange={(e) => setForm({...form, name: e.currentTarget.value})} data-testid="branches-name" />
          <TextInput label="Code" value={form.code} onChange={(e) => setForm({...form, code: e.currentTarget.value})} data-testid="branches-code" />
          <TextInput label="Address" value={form.address} onChange={(e) => setForm({...form, address: e.currentTarget.value})} />
          <Button onClick={() => createM.mutate({ name: form.name, code: form.code, address: form.address || null })} loading={createM.isPending} data-testid="branches-create">Create</Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
