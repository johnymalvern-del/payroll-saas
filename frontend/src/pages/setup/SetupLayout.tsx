import { Tabs, Stack, Title } from "@mantine/core";
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
