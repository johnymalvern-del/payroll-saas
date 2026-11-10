import { absoluteUrl, wrappedFetch } from "./client";

export type LeaveTypeOut = {
  id: string;
  name: string;
  code: string;
  unit: string;
  paid: boolean;
  accrual_method: string;
  accrual_amount: string | null;
  cycle: string;
  requires_approval: boolean;
  requires_document_after_days: number | null;
  allow_negative: boolean;
  max_carryover: string | null;
  is_active: boolean;
  row_version: number;
  approval_chain: string[];
  requires_payroll_admin_final: boolean;
  created_at: string;
  updated_at: string;
};

export type LeaveTypeListOut = {
  items: LeaveTypeOut[];
  next_cursor: string | null;
};

export type LeaveTypeIn = {
  name: string;
  code: string;
  unit?: string;
  paid?: boolean;
  accrual_method?: string;
  accrual_amount?: string | null;
  cycle?: string;
  requires_approval?: boolean;
  requires_document_after_days?: number | null;
  allow_negative?: boolean;
  max_carryover?: string | null;
  approval_chain?: string[];
  requires_payroll_admin_final?: boolean;
};

export type LeaveTypePatchIn = {
  row_version: number;
  name?: string;
  unit?: string;
  paid?: boolean;
  accrual_method?: string;
  accrual_amount?: string | null;
  cycle?: string;
  requires_approval?: boolean;
  requires_document_after_days?: number | null;
  allow_negative?: boolean;
  max_carryover?: string | null;
  approval_chain?: string[];
  requires_payroll_admin_final?: boolean;
};

export class LeaveApiError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;
  constructor(code: string, status: number, details?: Record<string, unknown>) {
    super(code);
    this.name = "LeaveApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export async function handleLeaveResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as {
      error?: { code?: string; details?: Record<string, unknown> };
    };
    throw new LeaveApiError(
      body.error?.code ?? `http_${res.status}`,
      res.status,
      body.error?.details,
    );
  }
  return (await res.json()) as T;
}

/** Existing convenience call used by pickers. Returns active types only. */
export async function fetchLeaveTypes(): Promise<LeaveTypeListOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/leave/types?is_active=true&limit=200"), {
      method: "GET",
      credentials: "include",
    }),
  );
  return handleLeaveResponse<LeaveTypeListOut>(res);
}

/** Paginated list — used by the admin page (L6) with explicit is_active. */
export async function fetchLeaveTypesPage(params: {
  is_active?: boolean;
  unit?: string;
  paid?: boolean;
  limit?: number;
  cursor?: string | null;
}): Promise<LeaveTypeListOut> {
  const qs = new URLSearchParams();
  if (params.is_active !== undefined) {
    qs.set("is_active", params.is_active ? "true" : "false");
  }
  if (params.unit) qs.set("unit", params.unit);
  if (params.paid !== undefined) qs.set("paid", params.paid ? "true" : "false");
  qs.set("limit", String(params.limit ?? 100));
  if (params.cursor) qs.set("cursor", params.cursor);
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/leave/types?${qs.toString()}`), {
      method: "GET",
      credentials: "include",
    }),
  );
  return handleLeaveResponse<LeaveTypeListOut>(res);
}

export async function fetchLeaveType(id: string): Promise<LeaveTypeOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/leave/types/${id}`), {
      method: "GET",
      credentials: "include",
    }),
  );
  return handleLeaveResponse<LeaveTypeOut>(res);
}

export async function createLeaveType(
  body: LeaveTypeIn,
): Promise<LeaveTypeOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/leave/types"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  return handleLeaveResponse<LeaveTypeOut>(res);
}

export async function patchLeaveType(
  id: string, body: LeaveTypePatchIn,
): Promise<LeaveTypeOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/leave/types/${id}`), {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  return handleLeaveResponse<LeaveTypeOut>(res);
}

export async function deactivateLeaveType(id: string): Promise<LeaveTypeOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/leave/types/${id}/deactivate`), {
      method: "POST",
      credentials: "include",
    }),
  );
  return handleLeaveResponse<LeaveTypeOut>(res);
}

export async function reactivateLeaveType(id: string): Promise<LeaveTypeOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/leave/types/${id}/reactivate`), {
      method: "POST",
      credentials: "include",
    }),
  );
  return handleLeaveResponse<LeaveTypeOut>(res);
}