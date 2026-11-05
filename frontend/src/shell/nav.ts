import type { IconName } from "../components/layout/Icon";

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
