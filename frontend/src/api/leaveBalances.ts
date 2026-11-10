import { absoluteUrl, wrappedFetch } from "./client";
import { handleLeaveResponse } from "./leaveTypes";

export type LeaveBalanceOut = {
  id: string;
  employee_id: string;
  leave_type_id: string;
  cycle_start: string;
  cycle_end: string;
  entitled: string;
  accrued: string;
  taken: string;
  pending: string;
  carried_in: string;
  adjusted: string;
  available: string;
  row_version: number;
  created_at: string;
  updated_at: string;
};

export type LeaveBalanceListOut = {
  items: LeaveBalanceOut[];
  next_cursor: string | null;
  accrued_as_of: string | null;
  accrual_stale: boolean;
};

export type BalanceAdjustIn = {
  employee_id: string;
  leave_type_id: string;
  cycle_start?: string | null;
  delta: string;
  reason: string;
};

export type BalanceAdjustOut = {
  balance: LeaveBalanceOut;
  ledger_entry_id: string;
};

export type AccrualRunIn = {
  as_of_date?: string | null;
};

export type AccrualRunOut = {
  employees_touched: number;
  rows_written: number;
  as_of: string;
};

export async function fetchLeaveBalances(params: {
  employee_id?: string;
  leave_type_id?: string;
  cycle_start_gte?: string;
  cycle_start_lte?: string;
  limit?: number;
  cursor?: string | null;
}): Promise<LeaveBalanceListOut> {
  const qs = new URLSearchParams();
  if (params.employee_id) qs.set("employee_id", params.employee_id);
  if (params.leave_type_id) qs.set("leave_type_id", params.leave_type_id);
  if (params.cycle_start_gte) qs.set("cycle_start_gte", params.cycle_start_gte);
  if (params.cycle_start_lte) qs.set("cycle_start_lte", params.cycle_start_lte);
  qs.set("limit", String(params.limit ?? 50));
  if (params.cursor) qs.set("cursor", params.cursor);
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/leave/balances?${qs.toString()}`), {
      method: "GET",
      credentials: "include",
    }),
  );
  return handleLeaveResponse<LeaveBalanceListOut>(res);
}

export async function adjustLeaveBalance(
  payload: BalanceAdjustIn,
): Promise<BalanceAdjustOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/leave/balances/adjust"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
  return handleLeaveResponse<BalanceAdjustOut>(res);
}

export async function runAccruals(
  params?: AccrualRunIn,
): Promise<AccrualRunOut> {
  const body = params ?? {};
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/leave/accruals/run"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  return handleLeaveResponse<AccrualRunOut>(res);
}