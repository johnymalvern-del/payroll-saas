import { absoluteUrl, wrappedFetch } from "./client";

export const ADJUSTMENT_OUTCOMES = [
  "worked",
  "leave",
  "sick",
  "absent",
  "day_off",
  "revert",
] as const;
export type AdjustmentOutcome = (typeof ADJUSTMENT_OUTCOMES)[number];

export type AdjustmentCreateRequest = {
  employee_id: string;
  work_date: string;
  outcome: AdjustmentOutcome;
  time_in: string | null;
  time_out: string | null;
  reason_code: string;
  note: string | null;
};

export type Adjustment = {
  id: string;
  employee_id: string;
  work_date: string;
  outcome: string;
  time_in: string | null;
  time_out: string | null;
  minutes: number | null;
  reason_code: string;
  note: string | null;
  created_at: string;
};

export type AdjustmentResult = {
  adjustment: Adjustment;
  day_status: string | null;
  day_worked_minutes: number | null;
  day_normal_minutes: number | null;
  day_overtime_minutes: number | null;
};

export async function createAdjustment(
  body: AdjustmentCreateRequest,
): Promise<AdjustmentResult> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/attendance/adjustments"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as {
      error?: { code?: string };
    };
    throw new Error(detail.error?.code ?? `http_${res.status}`);
  }
  return (await res.json()) as AdjustmentResult;
}

export type BulkAdjustItemIn = {
  employee_id: string;
  work_date: string;
  outcome: AdjustmentOutcome;
  time_in: string | null;
  time_out: string | null;
  reason_code: string;
  note: string | null;
};

export type BulkAdjustIn = {
  items: BulkAdjustItemIn[];
  token?: string;
};

export type BulkAdjustItemOut = {
  index: number;
  employee_id: string;
  work_date: string;
  ok: boolean;
  error_code?: string | null;
  error_message?: string | null;
  adjustment_id?: string | null;
};

export type BulkAdjustOut = {
  results: BulkAdjustItemOut[];
  applied: number;
  dry_run: boolean;
  token: string;
};

export class AdjustBulkError extends Error {
  code: string;
  status: number;
  results?: BulkAdjustItemOut[];
  constructor(code: string, status: number, results?: BulkAdjustItemOut[]) {
    super(code);
    this.name = "AdjustBulkError";
    this.code = code;
    this.status = status;
    this.results = results;
  }
}

export async function bulkAdjust(body: BulkAdjustIn): Promise<BulkAdjustOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/attendance/adjustments/bulk"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as {
      error?: { code?: string; details?: { results?: BulkAdjustItemOut[] } };
    };
    throw new AdjustBulkError(
      detail.error?.code ?? `http_${res.status}`,
      res.status,
      detail.error?.details?.results,
    );
  }
  return (await res.json()) as BulkAdjustOut;
}