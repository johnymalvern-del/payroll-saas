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

export async function fetchLeaveTypes(): Promise<LeaveTypeListOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/leave/types?is_active=true&limit=200"), {
      method: "GET",
      credentials: "include",
    }),
  );
  return handleLeaveResponse<LeaveTypeListOut>(res);
}