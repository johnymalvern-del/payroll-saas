import { getAccessToken } from "./client";
import { getTenantSlug } from "./tenant";

const BASE = "/api/v1";

export type EmployeeLookup = {
  id: string;
  employee_code: string;
  first_name: string;
  last_name: string;
};

export type PunchIn = {
  client_punch_id: string;
  employee_id: string;
  device_time: string;
  device_now_at_send?: string | null;
  method: string;
  photo_base64?: string | null;
  match_score?: number | string | null;
  liveness_passed?: boolean | null;
};

export type PunchOut = {
  id: string;
  effective_time: string;
  status: string;
  flags: string[];
};

function baseHeaders(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const slug = getTenantSlug();
  if (slug) h["X-Tenant-Slug"] = slug;
  const tok = getAccessToken();
  if (tok) h["Authorization"] = `Bearer ${tok}`;
  return h;
}

export async function resolveEmployeeByCode(
  code: string,
): Promise<EmployeeLookup | null> {
  const url =
    `${BASE}/employees?employee_code=${encodeURIComponent(code)}&limit=2`;
  const res = await fetch(url, { credentials: "include", headers: baseHeaders() });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg =
      (err as { error?: { message?: string } })?.error?.message ??
      `HTTP ${res.status}`;
    throw new Error(msg);
  }
  const body = (await res.json()) as { items?: EmployeeLookup[] };
  const items = body.items ?? [];
  if (items.length === 0) return null;
  if (items.length > 1) {
    throw new Error("employee_code_matches_more_than_one_employee");
  }
  return items[0];
}

export async function submitPunch(
  payload: PunchIn,
  deviceKey: string | null,
): Promise<PunchOut> {
  const h = baseHeaders();
  if (deviceKey) h["X-Device-Key"] = deviceKey;
  const res = await fetch(`${BASE}/punches`, {
    method: "POST",
    credentials: "include",
    headers: h,
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg =
      (err as { error?: { message?: string } })?.error?.message ??
      `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return (await res.json()) as PunchOut;
}

export function newClientPunchId(): string {
  const g = globalThis as { crypto?: Crypto };
  if (g.crypto?.randomUUID) return g.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (g.crypto?.getRandomValues) {
    g.crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
