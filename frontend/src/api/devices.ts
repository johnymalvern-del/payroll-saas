import { getAccessToken } from "./client";
import { getTenantSlug } from "./tenant";

const BASE = "/api/v1";

export type DeviceOut = {
  id: string;
  site_id: string;
  name: string;
  device_type: string;
  status: string;
  last_seen_at: string | null;
  last_sync_at: string | null;
  pending_punch_count: number;
  allows_code_only: boolean;
  require_photo_for_code: boolean;
  software_version: string | null;
  row_version: number;
};

export type DeviceCreateIn = {
  site_id: string;
  name: string;
  device_type: string;
  allows_code_only?: boolean;
  require_photo_for_code?: boolean;
  software_version?: string | null;
};

export type DeviceCreateOut = DeviceOut & { api_key: string };
export type DeviceRotateKeyOut = { id: string; api_key: string };
export type DeviceListOut = {
  items: DeviceOut[];
  next_cursor?: string | null;
  total?: number | null;
};

function authHeaders(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const slug = getTenantSlug();
  if (slug) h["X-Tenant-Slug"] = slug;
  const tok = getAccessToken();
  if (tok) h["Authorization"] = `Bearer ${tok}`;
  return h;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    credentials: "include",
    headers: authHeaders(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg =
      (err as { error?: { message?: string } })?.error?.message ??
      `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export const devicesApi = {
  list: () => request<DeviceListOut>("GET", "/devices"),
  create: (body: DeviceCreateIn) =>
    request<DeviceCreateOut>("POST", "/devices", body),
  rotateKey: (id: string) =>
    request<DeviceRotateKeyOut>("POST", `/devices/${id}/rotate-key`),
};
