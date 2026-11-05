import { useState } from "react";
import { Alert, Button, Group, Loader, Modal, Stack, Table, TextInput, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { departmentsApi, type Department } from "../../api/departments";

export function DepartmentsPage() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", code: "", parent_id: "" });

  const list = useQuery({ queryKey: ["departments"], queryFn: departmentsApi.list });
  const createM = useMutation({
    mutationFn: departmentsApi.create,
    onSuccess: () => { setOpen(false); setForm({ name: "", code: "", parent_id: "" }); qc.invalidateQueries({ queryKey: ["departments"] }); },
    onError: (e: Error) => setErr(e.message),
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Departments</Title>
        <Button onClick={() => { setErr(null); setOpen(true); }} data-testid="departments-add">Add department</Button>
      </Group>
      {err && <Alert color="red" data-testid="departments-error">{err}</Alert>}
      {list.isLoading ? <Loader /> : list.isError ? (
        <Alert color="red">Could not load departments.</Alert>
      ) : (
        <Table data-testid="departments-table">
          <Table.Thead><Table.Tr><Table.Th>Code</Table.Th><Table.Th>Name</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {(list.data?.items ?? []).map((d: Department) => (
              <Table.Tr key={d.id}><Table.Td>{d.code}</Table.Td><Table.Td>{d.name}</Table.Td></Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <Modal opened={open} onClose={() => setOpen(false)} title="New department">
        <Stack>
          <TextInput label="Name" value={form.name} onChange={(e) => setForm({...form, name: e.currentTarget.value})} data-testid="departments-name" />
          <TextInput label="Code" value={form.code} onChange={(e) => setForm({...form, code: e.currentTarget.value})} data-testid="departments-code" />
          <TextInput label="Parent id (optional)" value={form.parent_id} onChange={(e) => setForm({...form, parent_id: e.currentTarget.value})} />
          <Button onClick={() => createM.mutate({ name: form.name, code: form.code, parent_id: form.parent_id || null })} loading={createM.isPending} data-testid="departments-create">Create</Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
