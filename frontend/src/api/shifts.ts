import { getAccessToken } from "./client";
import { getTenantSlug } from "./tenant";

const BASE = "/api/v1";

function authHeaders(json = true): Record<string, string> {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  const slug = getTenantSlug();
  if (slug) h["X-Tenant-Slug"] = slug;
  const tok = getAccessToken();
  if (tok) h["Authorization"] = `Bearer ${tok}`;
  return h;
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    credentials: "include",
    headers: authHeaders(body !== undefined),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      (err as { error?: { message?: string } })?.error?.message ??
        `HTTP ${res.status}`,
    );
  }
  return (await res.json()) as T;
}

export type Shift = {
  id: string;
  name: string;
  start_time: string;
  length_minutes: number;
  unpaid_break_minutes: number;
  paid_break_minutes: number;
  grace_late_minutes: number;
  grace_early_minutes: number;
  rounding_minutes: number;
  rounding_mode: string;
  min_overtime_minutes: number;
  overtime_requires_approval: boolean;
  max_shift_minutes: number;
  match_tolerance_minutes: number;
  salaried_premium_mode: string;
  grace_mode: string;
  pay_early_arrival: boolean;
  is_active: boolean;
  row_version: number;
};

export type ShiftCreateIn = {
  name: string;
  start_time: string;
  length_minutes: number;
  max_shift_minutes: number;
  unpaid_break_minutes?: number;
  paid_break_minutes?: number;
  grace_late_minutes?: number;
  grace_early_minutes?: number;
  rounding_minutes?: number;
  rounding_mode?: string;
  min_overtime_minutes?: number;
  overtime_requires_approval?: boolean;
  match_tolerance_minutes?: number;
  salaried_premium_mode?: string;
  grace_mode?: string;
  pay_early_arrival?: boolean;
};

export type ShiftPatchIn = Partial<ShiftCreateIn> & { row_version: number; is_active?: boolean };
export type ShiftListOut = { items: Shift[]; next_cursor?: string | null; total?: number | null };

export const shiftsApi = {
  list: () => req<ShiftListOut>("GET", "/shifts"),
  create: (b: ShiftCreateIn) => req<Shift>("POST", "/shifts", b),
  patch: (id: string, b: ShiftPatchIn) => req<Shift>("PATCH", `/shifts/${id}`, b),
  remove: (id: string) => req<void>("DELETE", `/shifts/${id}`),
};
