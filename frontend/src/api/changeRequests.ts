import { absoluteUrl, wrappedFetch } from "./client";

export type ChangeRequestOut = {
  id: string;
  kind: string;
  employee_id: string;
  status: string;
  requested_by_user_id: string | null;
  requested_at: string;
  decided_by_user_id: string | null;
  decided_at: string | null;
  decision_note: string | null;
  applied_entity_id: string | null;
  row_version: number;
};

export type ChangeRequestListOut = {
  items: ChangeRequestOut[];
  next_cursor: string | null;
};

export class ChangeRequestsApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, status: number) {
    super(code);
    this.name = "ChangeRequestsApiError";
    this.code = code;
    this.status = status;
  }
}

export async function fetchChangeRequests(params: {
  status?: string;
  employee_id?: string;
  limit?: number;
  cursor?: string | null;
}): Promise<ChangeRequestListOut> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.employee_id) qs.set("employee_id", params.employee_id);
  qs.set("limit", String(params.limit ?? 100));
  if (params.cursor) qs.set("cursor", params.cursor);
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/change-requests?${qs.toString()}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw new Error(`http_${res.status}`);
  return (await res.json()) as ChangeRequestListOut;
}

export async function approveChangeRequest(id: string): Promise<ChangeRequestOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/change-requests/${id}/approve`), {
      method: "POST",
      credentials: "include",
    }),
  );
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as {
      error?: { code?: string };
    };
    throw new ChangeRequestsApiError(
      detail.error?.code ?? `http_${res.status}`,
      res.status,
    );
  }
  return (await res.json()) as ChangeRequestOut;
}

export async function rejectChangeRequest(
  id: string,
  note: string,
): Promise<ChangeRequestOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/change-requests/${id}/reject`), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    }),
  );
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as {
      error?: { code?: string };
    };
    throw new ChangeRequestsApiError(
      detail.error?.code ?? `http_${res.status}`,
      res.status,
    );
  }
  return (await res.json()) as ChangeRequestOut;
}

export async function cancelChangeRequest(id: string): Promise<ChangeRequestOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/change-requests/${id}/cancel`), {
      method: "POST",
      credentials: "include",
    }),
  );
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as {
      error?: { code?: string };
    };
    throw new ChangeRequestsApiError(
      detail.error?.code ?? `http_${res.status}`,
      res.status,
    );
  }
  return (await res.json()) as ChangeRequestOut;
}
