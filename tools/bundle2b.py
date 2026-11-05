"""Bundle 2B: SetupLayout + Sites/Branches/Departments pages + tests."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "frontend" / "src" / "pages" / "setup"

FILES = {
    "SetupLayout.tsx": '''import { Tabs, Stack, Title } from "@mantine/core";
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { strings } from "../../lib/strings";

const TABS = [
  { value: "sites", label: "Sites", path: "/setup/sites" },
  { value: "branches", label: "Branches", path: "/setup/branches" },
  { value: "departments", label: "Departments", path: "/setup/departments" },
  { value: "shifts", label: "Shifts", path: "/setup/shifts" },
  { value: "work-patterns", label: "Work patterns", path: "/setup/work-patterns" },
  { value: "public-holidays", label: "Public holidays", path: "/setup/public-holidays" },
  { value: "devices", label: strings.devices.title, path: "/setup/devices" },
];

export function SetupLayout() {
  const nav = useNavigate();
  const loc = useLocation();
  const current = TABS.find((t) => loc.pathname.startsWith(t.path))?.value ?? "sites";
  return (
    <Stack>
      <Title order={2}>Setup</Title>
      <Tabs value={current} onChange={(v) => {
        const t = TABS.find((x) => x.value === v);
        if (t) nav(t.path);
      }}>
        <Tabs.List>
          {TABS.map((t) => (
            <Tabs.Tab key={t.value} value={t.value}>{t.label}</Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      <Outlet />
    </Stack>
  );
}
''',

    "SitesPage.tsx": '''import { useState } from "react";
import { Alert, Button, Group, Loader, Modal, Stack, Table, TextInput, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { branchesApi, type Branch } from "../../api/branches";
import { sitesApi, type Site } from "../../api/sites";

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
      {err && <Alert color="red" data-testid="sites-error">{err}</Alert>}
      {sites.isLoading ? <Loader /> : sites.isError ? (
        <Alert color="red">Could not load sites.</Alert>
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
                <Table.Td>{s.timezone ?? "\\u2014"}</Table.Td>
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
''',

    "BranchesPage.tsx": '''import { useState } from "react";
import { Alert, Button, Group, Loader, Modal, Stack, Table, TextInput, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { branchesApi, type Branch } from "../../api/branches";

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
      {err && <Alert color="red" data-testid="branches-error">{err}</Alert>}
      {list.isLoading ? <Loader /> : list.isError ? (
        <Alert color="red">Could not load branches.</Alert>
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
''',

    "DepartmentsPage.tsx": '''import { useState } from "react";
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
''',
}

for name, content in FILES.items():
    (PAGES / name).write_text(content, encoding="utf-8")
    print(f"wrote src/pages/setup/{name}")