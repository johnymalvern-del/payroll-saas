import { describe, expect, it } from "vitest";
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
