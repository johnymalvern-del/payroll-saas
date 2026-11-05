"""Bundle 2C: Shifts (with rate rules) + WorkPatterns + PublicHolidays pages."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "frontend" / "src" / "pages" / "setup"

FILES = {
    "ShiftsPage.tsx": '''import { useState } from "react";
import { Alert, Button, Group, Loader, Modal, Stack, Table, TextInput, Title, NumberInput } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { rateRulesApi, type ShiftRateRule } from "../../api/rateRules";
import { shiftsApi, type Shift } from "../../api/shifts";

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
      {err && <Alert color="red" data-testid="shifts-error">{err}</Alert>}
      {list.isLoading ? <Loader /> : list.isError ? (
        <Alert color="red">Could not load shifts.</Alert>
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
          {rates.isLoading ? <Loader /> : rates.isError ? <Alert color="red">Could not load rate rules.</Alert> : (
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
''',

    "WorkPatternsPage.tsx": '''import { useState } from "react";
import { Alert, Button, Group, Loader, Modal, Stack, Table, TextInput, Title, NumberInput, Checkbox } from "@mantine/core";
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
''',

    "PublicHolidaysPage.tsx": '''import { useState } from "react";
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
''',
}

for name, content in FILES.items():
    (PAGES / name).write_text(content, encoding="utf-8")
    print(f"wrote src/pages/setup/{name}")