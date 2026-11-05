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

export type Site = {
  id: string;
  branch_id: string;
  name: string;
  code: string;
  site_type: string | null;
  address: string | null;
  timezone: string | null;
  latitude: number | string | null;
  longitude: number | string | null;
  geofence_radius_m: number | null;
  is_active: boolean;
  row_version: number;
};

export type SiteCreateIn = {
  branch_id: string;
  name: string;
  code: string;
  site_type?: string | null;
  address?: string | null;
  timezone?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  geofence_radius_m?: number | null;
};

export type SitePatchIn = Partial<SiteCreateIn> & { row_version: number; is_active?: boolean };
export type SiteListOut = { items: Site[]; next_cursor?: string | null; total?: number | null };

export const sitesApi = {
  list: () => req<SiteListOut>("GET", "/sites"),
  create: (b: SiteCreateIn) => req<Site>("POST", "/sites", b),
  patch: (id: string, b: SitePatchIn) => req<Site>("PATCH", `/sites/${id}`, b),
  remove: (id: string) => req<void>("DELETE", `/sites/${id}`),
};
