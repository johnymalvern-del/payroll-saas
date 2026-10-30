import { describe, expect, it } from "vitest";
import { buildNav } from "./nav";

describe("buildNav", () => {
  it("employee sees only Attendance", () => {
    const items = buildNav(["self_view", "self_submit", "attendance_view", "org_view"]);
    expect(items.map((i) => i.to)).toEqual(["/attendance"]);
  });

  it("manager sees Attendance and Exceptions", () => {
    const items = buildNav(["attendance_view", "exception_resolve", "attendance_adjust"]);
    expect(items.map((i) => i.to)).toEqual([
      "/attendance",
      "/attendance/exceptions",
      "/attendance/adjustments",
    ]);
  });

  it("hr sees admin-ish nav plus change requests", () => {
    const items = buildNav([
      "attendance_view",
      "exception_resolve",
      "attendance_adjust",
      "employee_crud",
      "org_manage",
      "payroll_preview",
      "pay_rate_view",
    ]);
    expect(items.map((i) => i.to)).toEqual([
      "/attendance",
      "/attendance/exceptions",
      "/attendance/adjustments",
      "/employees",
      "/setup",
      "/payroll/pay-periods",
      "/payroll/change-requests",
    ]);
  });

  it("payroll_admin gets audit log", () => {
    const items = buildNav([
      "payroll_preview",
      "audit_view",
      "employee_crud",
      "org_manage",
    ]);
    const paths = items.map((i) => i.to);
    expect(paths).toContain("/audit-log");
    expect(paths).toContain("/employees");
    expect(paths).toContain("/setup");
  });

  it("auditor sees only audit log", () => {
    const items = buildNav(["audit_view", "org_view", "payslip_view", "pay_rate_view"]);
    expect(items.map((i) => i.to)).toEqual(["/audit-log"]);
  });
});
