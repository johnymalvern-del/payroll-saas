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

export type ShiftRateRule = {
  id: string;
  shift_id: string;
  day_type: string;
  kind: string;
  tier: number;
  tier_up_to_minutes: number | null;
  method: string;
  value: string | number;
  flat_unit: string | null;
  effective_from: string;
  effective_to: string | null;
};

export type ShiftRateRuleCreateIn = {
  day_type: string;
  kind: string;
  tier: number;
  tier_up_to_minutes?: number | null;
  method: string;
  value: number | string;
  flat_unit?: string | null;
  effective_from: string;
  effective_to?: string | null;
};

export type ShiftRateRuleListOut = {
  items: ShiftRateRule[];
  next_cursor?: string | null;
  total?: number | null;
};

export const rateRulesApi = {
  list: (shiftId: string) =>
    req<ShiftRateRuleListOut>("GET", `/shifts/${shiftId}/rate-rules`),
  create: (shiftId: string, b: ShiftRateRuleCreateIn) =>
    req<ShiftRateRule>("POST", `/shifts/${shiftId}/rate-rules`, b),
  remove: (shiftId: string, ruleId: string) =>
    req<void>("DELETE", `/shifts/${shiftId}/rate-rules/${ruleId}`),
};
