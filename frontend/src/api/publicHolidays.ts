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

export type PublicHoliday = {
  id: string;
  holiday_date: string;
  name: string;
  site_id: string | null;
  department_id: string | null;
  is_working_day_override: boolean;
  is_active: boolean;
  row_version: number;
};

export type PublicHolidayCreateIn = {
  holiday_date: string;
  name: string;
  site_id?: string | null;
  department_id?: string | null;
  is_working_day_override?: boolean;
};

export type PublicHolidayPatchIn = {
  row_version: number;
  holiday_date?: string;
  name?: string;
  is_working_day_override?: boolean;
  is_active?: boolean;
};

export type PublicHolidayListOut = {
  items: PublicHoliday[];
  next_cursor?: string | null;
  total?: number | null;
};

export const publicHolidaysApi = {
  list: () => req<PublicHolidayListOut>("GET", "/public-holidays"),
  create: (b: PublicHolidayCreateIn) =>
    req<PublicHoliday>("POST", "/public-holidays", b),
  patch: (id: string, b: PublicHolidayPatchIn) =>
    req<PublicHoliday>("PATCH", `/public-holidays/${id}`, b),
  remove: (id: string) => req<void>("DELETE", `/public-holidays/${id}`),
};
