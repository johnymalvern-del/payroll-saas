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

export async function fetchLeaveBalances(params: {
  employee_id?: string;
  leave_type_id?: string;
  limit?: number;
  cursor?: string | null;
}): Promise<LeaveBalanceListOut> {
  const qs = new URLSearchParams();
  if (params.employee_id) qs.set("employee_id", params.employee_id);
  if (params.leave_type_id) qs.set("leave_type_id", params.leave_type_id);
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