"""P1b: nav rebuild (grouped) + nav.test rewrite + AppShell rebuild."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

# --- 1. nav.ts ---
(SRC / "shell" / "nav.ts").write_text('''import type { IconName } from "../components/layout/Icon";

export type NavItem = {
  label: string;
  to: string;
  icon: IconName;
};

export type NavGroup = {
  label: string | null;
  items: NavItem[];
};

const GROUP_ORDER: Array<string | null> = [
  null,
  "Attendance",
  "People",
  "Payroll",
  "Setup",
  "Audit",
];

const PERMISSION_NAV: Array<{
  permission: string;
  group: string | null;
  item: NavItem;
}> = [
  { permission: "self_view", group: null,
    item: { label: "Home", to: "/", icon: "home" } },
  { permission: "attendance_view", group: "Attendance",
    item: { label: "Attendance sheet", to: "/attendance", icon: "calendar" } },
  { permission: "exception_resolve", group: "Attendance",
    item: { label: "Exceptions", to: "/attendance/exceptions", icon: "alert" } },
  { permission: "attendance_adjust", group: "Attendance",
    item: { label: "Adjustments", to: "/attendance/adjustments", icon: "sliders" } },
  { permission: "attendance_view", group: "Attendance",
    item: { label: "Clock in", to: "/clock-in", icon: "clock" } },
  { permission: "employee_crud", group: "People",
    item: { label: "Employees", to: "/employees", icon: "users" } },
  { permission: "payroll_preview", group: "Payroll",
    item: { label: "Pay periods", to: "/payroll/pay-periods", icon: "dollar" } },
  { permission: "payroll_preview", group: "Payroll",
    item: { label: "Change requests", to: "/payroll/change-requests", icon: "check" } },
  { permission: "payslip_view", group: "Payroll",
    item: { label: "My payslips", to: "/payslips", icon: "file" } },
  { permission: "org_manage", group: "Setup",
    item: { label: "Setup", to: "/setup", icon: "settings" } },
  { permission: "audit_view", group: "Audit",
    item: { label: "Audit log", to: "/audit-log", icon: "audit" } },
];

export function buildNav(permissions: string[]): NavGroup[] {
  const set = new Set(permissions);
  const buckets = new Map<string | null, NavItem[]>();
  for (const { permission, group, item } of PERMISSION_NAV) {
    if (!set.has(permission)) continue;
    if (!buckets.has(group)) buckets.set(group, []);
    buckets.get(group)!.push(item);
  }
  return GROUP_ORDER.filter((g) => buckets.has(g)).map((g) => ({
    label: g,
    items: buckets.get(g)!,
  }));
}
''', encoding="utf-8")
print("wrote src/shell/nav.ts")

# --- 2. nav.test.ts ---
(SRC / "shell" / "nav.test.ts").write_text('''import { describe, expect, it } from "vitest";
import { buildNav } from "./nav";

function flat(perms: string[]) {
  return buildNav(perms).flatMap((g) => g.items.map((i) => i.to));
}

describe("buildNav", () => {
  it("employee sees Home, attendance sheet, clock in", () => {
    expect(
      flat(["self_view", "self_submit", "attendance_view", "org_view"]),
    ).toEqual(["/", "/attendance", "/clock-in"]);
  });

  it("manager sees attendance sheet, exceptions, adjustments, clock in", () => {
    expect(
      flat(["attendance_view", "exception_resolve", "attendance_adjust"]),
    ).toEqual([
      "/attendance",
      "/attendance/exceptions",
      "/attendance/adjustments",
      "/clock-in",
    ]);
  });

  it("hr sees attendance group plus employees, payroll, setup", () => {
    expect(
      flat([
        "attendance_view",
        "exception_resolve",
        "attendance_adjust",
        "employee_crud",
        "org_manage",
        "payroll_preview",
        "pay_rate_view",
      ]),
    ).toEqual([
      "/attendance",
      "/attendance/exceptions",
      "/attendance/adjustments",
      "/clock-in",
      "/employees",
      "/payroll/pay-periods",
      "/payroll/change-requests",
      "/setup",
    ]);
  });

  it("payroll_admin sees employees, payroll, setup, audit log", () => {
    expect(
      flat(["payroll_preview", "audit_view", "employee_crud", "org_manage"]),
    ).toEqual([
      "/employees",
      "/payroll/pay-periods",
      "/payroll/change-requests",
      "/setup",
      "/audit-log",
    ]);
  });

  it("auditor sees only payslips and audit log", () => {
    expect(
      flat(["audit_view", "org_view", "payslip_view", "pay_rate_view"]),
    ).toEqual(["/payslips", "/audit-log"]);
  });

  it("grouped output preserves group order and labels", () => {
    const groups = buildNav(["self_view", "attendance_view", "employee_crud"]);
    expect(groups.map((g) => g.label)).toEqual([null, "Attendance", "People"]);
  });
});
''', encoding="utf-8")
print("wrote src/shell/nav.test.ts")

# --- 3. AppShell.tsx rewrite ---
(SRC / "shell" / "AppShell.tsx").write_text('''import { Link as RouterLink, Outlet, useLocation } from "react-router-dom";
import {
  AppShell as MantineAppShell,
  Burger,
  Button,
  Group,
  Menu,
  ScrollArea,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useAuth } from "../auth/AuthContext";
import { useMe } from "../auth/useMe";
import { buildNav } from "./nav";
import { strings } from "../lib/strings";
import { Icon } from "../components/layout/Icon";

export function AppShell() {
  const { logout } = useAuth();
  const me = useMe();
  const location = useLocation();
  const [opened, { toggle, close }] = useDisclosure();
  const nav = buildNav(me.data?.permissions ?? []);

  return (
    <MantineAppShell
      header={{ height: 56 }}
      navbar={{ width: 248, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <MantineAppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
              aria-label="Toggle navigation"
            />
            <Text fw={700} size="md">
              {strings.appName}
            </Text>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <Button variant="subtle" size="xs">
                  {me.data?.username ?? "\\u2026"}
                </Button>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>
                  {strings.shell.roleLabel(me.data?.role ?? "")}
                </Menu.Label>
                <Menu.Item onClick={() => void logout()}>
                  {strings.shell.logout}
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </MantineAppShell.Header>

      <MantineAppShell.Navbar p="sm">
        <ScrollArea>
          <Stack gap={4}>
            {nav.map((group) => (
              <Stack key={group.label ?? "_home"} gap={2} mt="sm">
                {group.label ? (
                  <Text
                    size="xs"
                    c="dimmed"
                    fw={600}
                    tt="uppercase"
                    pl="sm"
                    pb={4}
                  >
                    {group.label}
                  </Text>
                ) : null}
                {group.items.map((item) => {
                  const active =
                    item.to === "/"
                      ? location.pathname === "/"
                      : location.pathname.startsWith(item.to);
                  return (
                    <UnstyledButton
                      key={item.to}
                      component={RouterLink}
                      to={item.to}
                      onClick={close}
                      style={{
                        display: "block",
                        padding: "8px 12px",
                        borderRadius: 8,
                        backgroundColor: active
                          ? "var(--mantine-color-navy-0)"
                          : "transparent",
                        color: active
                          ? "var(--mantine-color-navy-7)"
                          : "var(--mantine-color-text)",
                        fontWeight: active ? 600 : 400,
                      }}
                    >
                      <Group gap="sm" wrap="nowrap">
                        <Icon name={item.icon} size={18} />
                        <Text size="sm">{item.label}</Text>
                      </Group>
                    </UnstyledButton>
                  );
                })}
              </Stack>
            ))}
          </Stack>
        </ScrollArea>
      </MantineAppShell.Navbar>

      <MantineAppShell.Main>
        <Outlet />
      </MantineAppShell.Main>
    </MantineAppShell>
  );
}
''', encoding="utf-8")
print("wrote src/shell/AppShell.tsx")