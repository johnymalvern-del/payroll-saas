import { absoluteUrl, wrappedFetch } from "./client";

export type ExceptionStatus = "open" | "resolved" | "dismissed" | string;

export type ExceptionRow = {
  id: string;
  employee_id: string;
  work_date: string;
  type: string;
  source_ref: Record<string, unknown>;
  suggested_fix: Record<string, unknown>;
  status: ExceptionStatus;
  assigned_to: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  resolution: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type ExceptionList = {
  items: ExceptionRow[];
  next_cursor: string | null;
  total?: number | null;
};

export type ResolveAction = "apply_suggestion" | "custom" | "dismiss";

export type CustomAdjustment = {
  outcome: string;
  time_in: string | null;
  time_out: string | null;
  reason_code: string;
  note: string | null;
};

export type ResolveRequest = {
  action: ResolveAction;
  custom_adjustment: CustomAdjustment | null;
  note: string | null;
};

export type ResolveResponse = {
  exception: ExceptionRow;
  adjustment_id: string | null;
  day_status: string | null;
};

export type BulkResolveItemIn = {
  exception_id: string;
  action: ResolveAction;
  custom_adjustment?: CustomAdjustment | null;
  note?: string | null;
};

export type BulkResolveIn = {
  items: BulkResolveItemIn[];
  token?: string;
};

export type BulkResolveItemOut = {
  index: number;
  exception_id: string;
  ok: boolean;
  adjustment_id?: string | null;
  error_code?: string | null;
  error_message?: string | null;
};

export type BulkResolveOut = {
  results: BulkResolveItemOut[];
  applied: number;
  dry_run: boolean;
  token: string;
};

export class BulkApiError extends Error {
  code: string;
  status: number;
  details?: { results?: BulkResolveItemOut[] };
  constructor(
    code: string,
    status: number,
    details?: { results?: BulkResolveItemOut[] },
  ) {
    super(code);
    this.name = "BulkApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export async function fetchExceptions(params: {
  status?: string;
  type?: string;
  fromDate?: string;
  toDate?: string;
  limit?: number;
  cursor?: string | null;
}): Promise<ExceptionList> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.type) qs.set("type", params.type);
  if (params.fromDate) qs.set("from_date", params.fromDate);
  if (params.toDate) qs.set("to_date", params.toDate);
  qs.set("limit", String(params.limit ?? 100));
  if (params.cursor) qs.set("cursor", params.cursor);
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/attendance/exceptions?${qs.toString()}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw new Error(`http_${res.status}`);
  const data = (await res.json()) as Record<string, unknown>;
  return {
    items: Array.isArray(data.items) ? (data.items as ExceptionRow[]) : [],
    next_cursor:
      typeof data.next_cursor === "string" ? data.next_cursor : null,
    total: typeof data.total === "number" ? data.total : null,
  };
}

export async function resolveException(
  exceptionId: string,
  body: ResolveRequest,
): Promise<ResolveResponse> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(`/api/v1/attendance/exceptions/${exceptionId}/resolve`),
      {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  );
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as {
      error?: { code?: string };
    };
    throw new Error(detail.error?.code ?? `http_${res.status}`);
  }
  return (await res.json()) as ResolveResponse;
}

export async function bulkResolveExceptions(
  body: BulkResolveIn,
): Promise<BulkResolveOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl("/api/v1/attendance/exceptions/bulk_resolve"),
      {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  );
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as {
      error?: { code?: string; details?: { results?: BulkResolveItemOut[] } };
    };
    throw new BulkApiError(
      detail.error?.code ?? `http_${res.status}`,
      res.status,
      detail.error?.details,
    );
  }
  return (await res.json()) as BulkResolveOut;
}