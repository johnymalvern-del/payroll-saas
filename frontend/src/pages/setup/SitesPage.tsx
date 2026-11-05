import { useState } from "react";
import { Alert, Button, Group, Loader, Modal, Stack, Table, TextInput, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { branchesApi, type Branch } from "../../api/branches";
import { sitesApi, type Site } from "../../api/sites";
import { colors } from "../../theme/colors";

export function SitesPage() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ branch_id: "", name: "", code: "", timezone: "Africa/Johannesburg", site_type: "", address: "" });

  const sites = useQuery({ queryKey: ["sites"], queryFn: sitesApi.list });
  const branches = useQuery({ queryKey: ["branches"], queryFn: branchesApi.list });

  const createM = useMutation({
    mutationFn: sitesApi.create,
    onSuccess: () => {
      setOpen(false);
      setForm({ branch_id: "", name: "", code: "", timezone: "Africa/Johannesburg", site_type: "", address: "" });
      qc.invalidateQueries({ queryKey: ["sites"] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Sites</Title>
        <Button onClick={() => { setErr(null); setOpen(true); }} data-testid="sites-add">Add site</Button>
      </Group>
      {err && <Alert color={colors.problem} data-testid="sites-error">{err}</Alert>}
      {sites.isLoading ? <Loader /> : sites.isError ? (
        <Alert color={colors.problem}>Could not load sites.</Alert>
      ) : (
        <Table data-testid="sites-table">
          <Table.Thead><Table.Tr>
            <Table.Th>Code</Table.Th><Table.Th>Name</Table.Th><Table.Th>Branch</Table.Th><Table.Th>Timezone</Table.Th>
          </Table.Tr></Table.Thead>
          <Table.Tbody>
            {(sites.data?.items ?? []).map((s: Site) => (
              <Table.Tr key={s.id}>
                <Table.Td>{s.code}</Table.Td>
                <Table.Td>{s.name}</Table.Td>
                <Table.Td>{s.branch_id.slice(0, 8)}</Table.Td>
                <Table.Td>{s.timezone ?? "\u2014"}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <Modal opened={open} onClose={() => setOpen(false)} title="New site">
        <Stack>
          <TextInput label="Branch id" value={form.branch_id} onChange={(e) => setForm({...form, branch_id: e.currentTarget.value})} data-testid="sites-branch" placeholder={(branches.data?.items ?? []).map((b: Branch) => `${b.code}: ${b.id}`).join(" | ")} />
          <TextInput label="Name" value={form.name} onChange={(e) => setForm({...form, name: e.currentTarget.value})} data-testid="sites-name" />
          <TextInput label="Code" value={form.code} onChange={(e) => setForm({...form, code: e.currentTarget.value})} data-testid="sites-code" />
          <TextInput label="Timezone" value={form.timezone} onChange={(e) => setForm({...form, timezone: e.currentTarget.value})} data-testid="sites-tz" />
          <TextInput label="Address" value={form.address} onChange={(e) => setForm({...form, address: e.currentTarget.value})} />
          <Button onClick={() => createM.mutate({ branch_id: form.branch_id, name: form.name, code: form.code, timezone: form.timezone || null, address: form.address || null })} loading={createM.isPending} data-testid="sites-create">Create</Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
