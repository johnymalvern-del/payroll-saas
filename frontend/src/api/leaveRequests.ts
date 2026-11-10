import { absoluteUrl, wrappedFetch } from "./client";
import { handleLeaveResponse } from "./leaveTypes";

export type LeaveRequestDayOut = {
  id: string;
  leave_request_id: string;
  work_date: string;
  days: string;
};

export type LeaveApprovalStepOut = {
  id: string;
  leave_request_id: string;
  step_no: number;
  approver_user_id: string | null;
  approver_role: string | null;
  status: string;
  decided_at: string | null;
  note: string | null;
  created_at: string;
};

export type LeaveRequestOut = {
  id: string;
  employee_id: string;
  leave_type_id: string;
  from_date: string;
  to_date: string;
  days_requested: string;
  reason: string | null;
  status: string;
  submitted_at: string | null;
  decided_at: string | null;
  decided_by_user_id: string | null;
  decision_note: string | null;
  row_version: number;
  created_at: string;
  updated_at: string;
  captured_by_user_id: string | null;
  days: LeaveRequestDayOut[];
  steps: LeaveApprovalStepOut[];
  employee_code: string | null;
  employee_name: string | null;
  leave_type_name: string | null;
};

export type LeaveRequestListOut = {
  items: LeaveRequestOut[];
  next_cursor: string | null;
};

export type LeaveRequestCreateIn = {
  employee_id?: string | null;
  leave_type_id: string;
  from_date: string;
  to_date: string;
  reason?: string | null;
};

export type LeaveRequestPatchIn = {
  row_version: number;
  from_date?: string;
  to_date?: string;
  reason?: string | null;
};

export type StepDecideIn = {
  approve: boolean;
  note?: string | null;
};

export async function fetchLeaveRequests(params: {
  employee_id?: string;
  status?: string;
  from_date_gte?: string;
  to_date_lte?: string;
  awaiting_approver_user_id?: string;
  limit?: number;
  cursor?: string | null;
}): Promise<LeaveRequestListOut> {
  const qs = new URLSearchParams();
  if (params.employee_id) qs.set("employee_id", params.employee_id);
  if (params.status) qs.set("status", params.status);
  if (params.from_date_gte) qs.set("from_date_gte", params.from_date_gte);
  if (params.to_date_lte) qs.set("to_date_lte", params.to_date_lte);
  if (params.awaiting_approver_user_id) {
    qs.set("awaiting_approver_user_id", params.awaiting_approver_user_id);
  }
  qs.set("limit", String(params.limit ?? 50));
  if (params.cursor) qs.set("cursor", params.cursor);
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/leave/requests?${qs.toString()}`), {
      method: "GET",
      credentials: "include",
    }),
  );
  return handleLeaveResponse<LeaveRequestListOut>(res);
}

export async function fetchLeaveRequest(id: string): Promise<LeaveRequestOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/leave/requests/${id}`), {
      method: "GET",
      credentials: "include",
    }),
  );
  return handleLeaveResponse<LeaveRequestOut>(res);
}

export async function createLeaveRequest(
  body: LeaveRequestCreateIn,
): Promise<LeaveRequestOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/leave/requests"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  return handleLeaveResponse<LeaveRequestOut>(res);
}

export async function updateLeaveRequest(
  id: string, body: LeaveRequestPatchIn,
): Promise<LeaveRequestOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/leave/requests/${id}`), {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  return handleLeaveResponse<LeaveRequestOut>(res);
}

export async function submitLeaveRequest(
  id: string,
): Promise<LeaveRequestOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/leave/requests/${id}/submit`), {
      method: "POST",
      credentials: "include",
    }),
  );
  return handleLeaveResponse<LeaveRequestOut>(res);
}

export async function cancelLeaveRequest(
  id: string,
): Promise<LeaveRequestOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/leave/requests/${id}/cancel`), {
      method: "POST",
      credentials: "include",
    }),
  );
  return handleLeaveResponse<LeaveRequestOut>(res);
}

export async function decideStep(
  requestId: string,
  stepId: string,
  body: StepDecideIn,
): Promise<LeaveRequestOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(
        `/api/v1/leave/requests/${requestId}/steps/${stepId}/decide`,
      ),
      {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  );
  return handleLeaveResponse<LeaveRequestOut>(res);
}