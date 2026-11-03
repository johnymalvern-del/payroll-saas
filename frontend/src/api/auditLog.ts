import { absoluteUrl, wrappedFetch } from "./client";

export type AuditLogOut = {
  id: string;
  occurred_at: string;
  actor_user_id: string | null;
  actor_role: string | null;
  entity_type: string;
  entity_id: string | null;
  action: string;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  reason: string | null;
  ip_address: string | null;
  request_id: string | null;
};

export type AuditLogListOut = {
  items: AuditLogOut[];
  next_cursor: string | null;
  total: number | null;
  occurred_from_applied: string;
  occurred_to_applied: string;
};

export type AuditLogFilters = {
  occurred_from?: string;
  occurred_to?: string;
  actor_user_id?: string;
  actor_role?: string;
  entity_type?: string;
  entity_id?: string;
  action?: string;
  request_id?: string;
  reason?: string;
};

export class AuditLogApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, status: number) {
    super(code);
    this.name = "AuditLogApiError";
    this.code = code;
    this.status = status;
  }
}

async function parseError(res: Response): Promise<AuditLogApiError> {
  const detail = (await res.json().catch(() => ({}))) as {
    error?: { code?: string };
  };
  return new AuditLogApiError(
    detail.error?.code ?? `http_${res.status}`,
    res.status,
  );
}

export async function fetchAuditLog(params: {
  filters?: AuditLogFilters;
  limit?: number;
  cursor?: string | null;
  include_total?: boolean;
}): Promise<AuditLogListOut> {
  const qs = new URLSearchParams();
  const f = params.filters ?? {};
  if (f.occurred_from) qs.set("occurred_from", f.occurred_from);
  if (f.occurred_to) qs.set("occurred_to", f.occurred_to);
  if (f.actor_user_id) qs.set("actor_user_id", f.actor_user_id);
  if (f.actor_role) qs.set("actor_role", f.actor_role);
  if (f.entity_type) qs.set("entity_type", f.entity_type);
  if (f.entity_id) qs.set("entity_id", f.entity_id);
  if (f.action) qs.set("action", f.action);
  if (f.request_id) qs.set("request_id", f.request_id);
  if (f.reason) qs.set("reason", f.reason);
  qs.set("limit", String(params.limit ?? 100));
  if (params.cursor) qs.set("cursor", params.cursor);
  if (params.include_total) qs.set("include_total", "true");
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/audit-log?${qs.toString()}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as AuditLogListOut;
}

export async function fetchAuditLogEntry(id: string): Promise<AuditLogOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/audit-log/${id}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as AuditLogOut;
}
