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

export type WorkPatternDay = {
  id: string;
  work_pattern_id: string;
  day_index: number;
  is_expected: boolean;
  expected_shift_id: string | null;
};

export type WorkPattern = {
  id: string;
  name: string;
  cycle_length_days: number;
  anchor_date: string;
  is_active: boolean;
  row_version: number;
  days: WorkPatternDay[];
};

export type WorkPatternDayIn = {
  day_index: number;
  is_expected: boolean;
  expected_shift_id?: string | null;
};

export type WorkPatternCreateIn = {
  name: string;
  cycle_length_days: number;
  anchor_date: string;
  days: WorkPatternDayIn[];
};

export type WorkPatternPatchIn = Partial<WorkPatternCreateIn> & {
  row_version: number;
  is_active?: boolean;
};

export type WorkPatternListOut = {
  items: Omit<WorkPattern, "days">[];
  next_cursor?: string | null;
  total?: number | null;
};

export const workPatternsApi = {
  list: () => req<WorkPatternListOut>("GET", "/work-patterns"),
  get: (id: string) => req<WorkPattern>("GET", `/work-patterns/${id}`),
  create: (b: WorkPatternCreateIn) =>
    req<WorkPattern>("POST", "/work-patterns", b),
  patch: (id: string, b: WorkPatternPatchIn) =>
    req<WorkPattern>("PATCH", `/work-patterns/${id}`, b),
  remove: (id: string) => req<void>("DELETE", `/work-patterns/${id}`),
};
