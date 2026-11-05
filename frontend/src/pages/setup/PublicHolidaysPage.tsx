import { useState } from "react";
import { Alert, Button, Group, Loader, Modal, Stack, Table, TextInput, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { publicHolidaysApi, type PublicHoliday } from "../../api/publicHolidays";

export function PublicHolidaysPage() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ holiday_date: "", name: "" });

  const list = useQuery({ queryKey: ["public-holidays"], queryFn: publicHolidaysApi.list });
  const createM = useMutation({
    mutationFn: publicHolidaysApi.create,
    onSuccess: () => { setOpen(false); setForm({ holiday_date: "", name: "" }); qc.invalidateQueries({ queryKey: ["public-holidays"] }); },
    onError: (e: Error) => setErr(e.message),
  });
  const deactivateM = useMutation({
    mutationFn: (h: PublicHoliday) => publicHolidaysApi.patch(h.id, { row_version: h.row_version, is_active: false }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["public-holidays"] }),
    onError: (e: Error) => setErr(e.message),
  });

  return (
    <Stack>
      <Alert color="blue">Country-level ZA holidays load via the loader CLI. This list is for tenant overrides (site/department-specific).</Alert>
      <Group justify="space-between">
        <Title order={3}>Public holidays</Title>
        <Button onClick={() => { setErr(null); setOpen(true); }} data-testid="ph-add">Add override</Button>
      </Group>
      {err && <Alert color="red" data-testid="ph-error">{err}</Alert>}
      {list.isLoading ? <Loader /> : list.isError ? (
        <Alert color="red">Could not load public holidays.</Alert>
      ) : (
        <Table data-testid="ph-table">
          <Table.Thead><Table.Tr><Table.Th>Date</Table.Th><Table.Th>Name</Table.Th><Table.Th>Active</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {(list.data?.items ?? []).map((h: PublicHoliday) => (
              <Table.Tr key={h.id}>
                <Table.Td>{h.holiday_date}</Table.Td>
                <Table.Td>{h.name}</Table.Td>
                <Table.Td>{h.is_active ? "yes" : "no"}</Table.Td>
                <Table.Td>
                  {h.is_active && (
                    <Button size="xs" variant="light" onClick={() => deactivateM.mutate(h)}>Deactivate</Button>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <Modal opened={open} onClose={() => setOpen(false)} title="New public holiday override">
        <Stack>
          <TextInput label="Date (YYYY-MM-DD)" value={form.holiday_date} onChange={(e) => setForm({...form, holiday_date: e.currentTarget.value})} data-testid="ph-date" />
          <TextInput label="Name" value={form.name} onChange={(e) => setForm({...form, name: e.currentTarget.value})} data-testid="ph-name" />
          <Button onClick={() => createM.mutate(form)} loading={createM.isPending} data-testid="ph-create">Create</Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
