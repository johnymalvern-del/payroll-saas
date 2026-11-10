import { describe, expect, it } from "vitest";
import { buildNav } from "./nav";

function flat(perms: string[]) {
  return buildNav(perms).flatMap((g) => g.items.map((i) => i.to));
}

describe("buildNav", () => {
  it("employee sees Home, attendance sheet, clock in, my leave", () => {
    expect(
      flat(["self_view", "self_submit", "attendance_view", "org_view"]),
    ).toEqual(["/", "/attendance", "/clock-in", "/leave"]);
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

  it("hr sees attendance group plus employees, leave admin, payroll, setup", () => {
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
      "/leave/admin",
      "/payroll/employee-payroll",
      "/payroll/pay-periods",
      "/payroll/change-requests",
      "/payroll/salary-structures",
      "/setup",
    ]);
  });

  it("payroll_admin sees employees, leave admin, payroll, setup, audit log", () => {
    expect(
      flat(["payroll_preview", "audit_view", "employee_crud", "org_manage"]),
    ).toEqual([
      "/employees",
      "/leave/admin",
      "/payroll/pay-periods",
      "/payroll/change-requests",
      "/setup",
      "/audit-log",
    ]);
  });

  it("auditor sees employee payroll, salary structures, payslips and audit log", () => {
    expect(
      flat(["audit_view", "org_view", "payslip_view", "pay_rate_view"]),
    ).toEqual([
      "/payroll/employee-payroll",
      "/payroll/salary-structures",
      "/payslips",
      "/audit-log",
    ]);
  });

  it("grouped output preserves group order and labels", () => {
    const groups = buildNav(["self_view", "attendance_view", "employee_crud"]);
    expect(groups.map((g) => g.label)).toEqual([null, "Attendance", "People"]);
  });

  it("approver with leave_approve sees My Approvals in the People group", () => {
    expect(flat(["leave_approve"])).toEqual(["/leave/approvals"]);
  });

  it("approver also holding self_view sees My Leave before My Approvals", () => {
    expect(
      flat(["self_view", "leave_approve"]),
    ).toEqual(["/", "/leave", "/leave/approvals"]);
  });
});