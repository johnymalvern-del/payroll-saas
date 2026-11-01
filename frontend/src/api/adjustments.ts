import { absoluteUrl, wrappedFetch } from "./client";

export const ADJUSTMENT_OUTCOMES = [
  "worked",
  "leave",
  "sick",
  "absent",
  "day_off",
] as const;
export type AdjustmentOutcome = (typeof ADJUSTMENT_OUTCOMES)[number];

export type AdjustmentCreateRequest = {
  employee_id: string;
  work_date: string;
  outcome: AdjustmentOutcome | "revert";
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
