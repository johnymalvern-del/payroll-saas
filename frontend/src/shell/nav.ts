export type NavItem = {
  label: string;
  to: string;
};

const PERMISSION_NAV: Array<{ permission: string; item: NavItem }> = [
  { permission: "attendance_view", item: { label: "Attendance", to: "/attendance" } },
  { permission: "exception_resolve", item: { label: "Exceptions", to: "/attendance/exceptions" } },
  { permission: "attendance_adjust", item: { label: "Adjustments", to: "/attendance/adjustments" } },
  { permission: "employee_crud", item: { label: "Employees", to: "/employees" } },
  { permission: "org_manage", item: { label: "Setup", to: "/setup" } },
  { permission: "payroll_preview", item: { label: "Pay periods", to: "/payroll/pay-periods" } },
  // Change requests is an approval workflow, not a read-only view; gate it on
  // a payroll-run permission (payroll_preview) rather than pay_rate_view so
  // read-only auditors (audit_view + pay_rate_view) do not see it.
  { permission: "payroll_preview", item: { label: "Change requests", to: "/payroll/change-requests" } },
  { permission: "audit_view", item: { label: "Audit log", to: "/audit-log" } },
];

export function buildNav(permissions: string[]): NavItem[] {
  const set = new Set(permissions);
  return PERMISSION_NAV.filter((entry) => set.has(entry.permission)).map(
    (entry) => entry.item,
  );
}