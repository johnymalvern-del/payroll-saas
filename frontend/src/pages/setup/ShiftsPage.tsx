import { useState } from "react";
import { Alert, Button, Group, Loader, Modal, Stack, Table, TextInput, Title, NumberInput } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { rateRulesApi, type ShiftRateRule } from "../../api/rateRules";
import { shiftsApi, type Shift } from "../../api/shifts";
import { colors } from "../../theme/colors";

export function ShiftsPage() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", start_time: "08:00", length_minutes: 480, max_shift_minutes: 720 });
  const [selShift, setSelShift] = useState<Shift | null>(null);

  const list = useQuery({ queryKey: ["shifts"], queryFn: shiftsApi.list });
  const rates = useQuery({
    queryKey: ["shift-rates", selShift?.id],
    queryFn: () => rateRulesApi.list(selShift!.id),
    enabled: !!selShift,
  });

  const createM = useMutation({
    mutationFn: shiftsApi.create,
    onSuccess: () => { setOpen(false); setForm({ name: "", start_time: "08:00", length_minutes: 480, max_shift_minutes: 720 }); qc.invalidateQueries({ queryKey: ["shifts"] }); },
    onError: (e: Error) => setErr(e.message),
  });

  const [rateForm, setRateForm] = useState({ day_type: "", kind: "", tier: 1, method: "", value: "", effective_from: "" });
  const addRateM = useMutation({
    mutationFn: () => rateRulesApi.create(selShift!.id, { ...rateForm, value: rateForm.value }),
    onSuccess: () => { setRateForm({ day_type: "", kind: "", tier: 1, method: "", value: "", effective_from: "" }); qc.invalidateQueries({ queryKey: ["shift-rates", selShift?.id] }); },
    onError: (e: Error) => setErr(e.message),
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Shifts</Title>
        <Button onClick={() => { setErr(null); setOpen(true); }} data-testid="shifts-add">Add shift</Button>
      </Group>
      {err && <Alert color={colors.problem} data-testid="shifts-error">{err}</Alert>}
      {list.isLoading ? <Loader /> : list.isError ? (
        <Alert color={colors.problem}>Could not load shifts.</Alert>
      ) : (
        <Table data-testid="shifts-table">
          <Table.Thead><Table.Tr>
            <Table.Th>Name</Table.Th><Table.Th>Start</Table.Th><Table.Th>Length</Table.Th><Table.Th>Max</Table.Th><Table.Th />
          </Table.Tr></Table.Thead>
          <Table.Tbody>
            {(list.data?.items ?? []).map((s: Shift) => (
              <Table.Tr key={s.id}>
                <Table.Td>{s.name}</Table.Td>
                <Table.Td>{s.start_time}</Table.Td>
                <Table.Td>{s.length_minutes}</Table.Td>
                <Table.Td>{s.max_shift_minutes}</Table.Td>
                <Table.Td>
                  <Button size="xs" variant="light" onClick={() => { setErr(null); setSelShift(s); }}>Rate table</Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <Modal opened={open} onClose={() => setOpen(false)} title="New shift">
        <Stack>
          <TextInput label="Name" value={form.name} onChange={(e) => setForm({...form, name: e.currentTarget.value})} data-testid="shifts-name" />
          <TextInput label="Start time (HH:MM)" value={form.start_time} onChange={(e) => setForm({...form, start_time: e.currentTarget.value})} data-testid="shifts-start" />
          <NumberInput label="Length (minutes)" value={form.length_minutes} onChange={(v) => setForm({...form, length_minutes: Number(v) || 0})} data-testid="shifts-length" />
          <NumberInput label="Max shift (minutes)" value={form.max_shift_minutes} onChange={(v) => setForm({...form, max_shift_minutes: Number(v) || 0})} data-testid="shifts-max" />
          <Button onClick={() => createM.mutate(form)} loading={createM.isPending} data-testid="shifts-create">Create</Button>
        </Stack>
      </Modal>
      <Modal opened={!!selShift} onClose={() => setSelShift(null)} title={`Rate table — ${selShift?.name ?? ""}`} size="lg">
        <Stack>
          {rates.isLoading ? <Loader /> : rates.isError ? <Alert color={colors.problem}>Could not load rate rules.</Alert> : (
            <Table data-testid="rate-rules-table">
              <Table.Thead><Table.Tr>
                <Table.Th>Day type</Table.Th><Table.Th>Kind</Table.Th><Table.Th>Tier</Table.Th><Table.Th>Method</Table.Th><Table.Th>Value</Table.Th><Table.Th>From</Table.Th>
              </Table.Tr></Table.Thead>
              <Table.Tbody>
                {(rates.data?.items ?? []).map((r: ShiftRateRule) => (
                  <Table.Tr key={r.id}>
                    <Table.Td>{r.day_type}</Table.Td>
                    <Table.Td>{r.kind}</Table.Td>
                    <Table.Td>{r.tier}</Table.Td>
                    <Table.Td>{r.method}</Table.Td>
                    <Table.Td>{String(r.value)}</Table.Td>
                    <Table.Td>{r.effective_from}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
          <TextInput label="Day type (e.g. weekday/weekend)" value={rateForm.day_type} onChange={(e) => setRateForm({...rateForm, day_type: e.currentTarget.value})} data-testid="rr-day-type" />
          <TextInput label="Kind (e.g. base/overtime)" value={rateForm.kind} onChange={(e) => setRateForm({...rateForm, kind: e.currentTarget.value})} data-testid="rr-kind" />
          <NumberInput label="Tier" value={rateForm.tier} onChange={(v) => setRateForm({...rateForm, tier: Number(v) || 1})} />
          <TextInput label="Method (e.g. multiplier/flat)" value={rateForm.method} onChange={(e) => setRateForm({...rateForm, method: e.currentTarget.value})} data-testid="rr-method" />
          <TextInput label="Value" value={rateForm.value} onChange={(e) => setRateForm({...rateForm, value: e.currentTarget.value})} data-testid="rr-value" />
          <TextInput label="Effective from (YYYY-MM-DD)" value={rateForm.effective_from} onChange={(e) => setRateForm({...rateForm, effective_from: e.currentTarget.value})} data-testid="rr-from" />
          <Button onClick={() => addRateM.mutate()} loading={addRateM.isPending} data-testid="rr-create">Add rate rule</Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
