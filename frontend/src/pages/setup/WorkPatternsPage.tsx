import { useState } from "react";
import { Alert, Button, Checkbox, Group, Loader, Modal, NumberInput, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { workPatternsApi, type WorkPatternDayIn } from "../../api/workPatterns";

export function WorkPatternsPage() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", cycle_length_days: 7, anchor_date: new Date().toISOString().slice(0, 10) });
  const [days, setDays] = useState<WorkPatternDayIn[]>(
    Array.from({ length: 7 }, (_, i) => ({ day_index: i, is_expected: i < 5, expected_shift_id: null })),
  );

  const list = useQuery({ queryKey: ["work-patterns"], queryFn: workPatternsApi.list });
  const createM = useMutation({
    mutationFn: workPatternsApi.create,
    onSuccess: () => { setOpen(false); qc.invalidateQueries({ queryKey: ["work-patterns"] }); },
    onError: (e: Error) => setErr(e.message),
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Work patterns</Title>
        <Button onClick={() => { setErr(null); setOpen(true); }} data-testid="wp-add">Add work pattern</Button>
      </Group>
      {err && <Alert color="red" data-testid="wp-error">{err}</Alert>}
      {list.isLoading ? <Loader /> : list.isError ? (
        <Alert color="red">Could not load work patterns.</Alert>
      ) : (
        <Table data-testid="wp-table">
          <Table.Thead><Table.Tr><Table.Th>Name</Table.Th><Table.Th>Cycle</Table.Th><Table.Th>Anchor</Table.Th><Table.Th>Active</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {(list.data?.items ?? []).map((w) => (
              <Table.Tr key={w.id}>
                <Table.Td>{w.name}</Table.Td>
                <Table.Td>{w.cycle_length_days}</Table.Td>
                <Table.Td>{w.anchor_date}</Table.Td>
                <Table.Td>{w.is_active ? "yes" : "no"}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <Modal opened={open} onClose={() => setOpen(false)} title="New work pattern" size="lg">
        <Stack>
          <TextInput label="Name" value={form.name} onChange={(e) => setForm({...form, name: e.currentTarget.value})} data-testid="wp-name" />
          <NumberInput label="Cycle length days" value={form.cycle_length_days} onChange={(v) => setForm({...form, cycle_length_days: Number(v) || 7})} />
          <TextInput label="Anchor date (YYYY-MM-DD)" value={form.anchor_date} onChange={(e) => setForm({...form, anchor_date: e.currentTarget.value})} data-testid="wp-anchor" />
          <Text fw={500}>Days</Text>
          {days.map((d, i) => (
            <Group key={i}>
              <Text w={40}>Day {d.day_index}</Text>
              <Checkbox label="Expected" checked={d.is_expected} onChange={(e) => {
                const next = [...days]; next[i] = { ...d, is_expected: e.currentTarget.checked }; setDays(next);
              }} data-testid={`wp-day-${i}`} />
            </Group>
          ))}
          <Button onClick={() => createM.mutate({ name: form.name, cycle_length_days: form.cycle_length_days, anchor_date: form.anchor_date, days })} loading={createM.isPending} data-testid="wp-create">Create</Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
