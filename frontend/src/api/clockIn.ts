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
  latitude?: number | string | null;
  longitude?: number | string | null;
  gps_accuracy_m?: number | string | null;
};

export type PunchOut = {
  id: string;
  effective_time: string;
  status: string;
  flags: string[];
  site_id?: string | null;
  site_name?: string | null;
  latitude?: string | null;
  longitude?: string | null;
  gps_accuracy_m?: string | null;
  geofence_result?: string | null;
  geofence_reason?: string | null;
  distance_m?: string | null;
  warnings?: string[];
};

export type PositionResult =
  | { ok: true; latitude: number; longitude: number; gps_accuracy_m: number }
  | { ok: false; reason: "unsupported" | "denied" | "timeout" | "unavailable" };

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

/**
 * Read the device's current position for attendance verification.
 *
 * Returns a discriminated result rather than throwing: a clock-in must still
 * be possible when location is unavailable, and the caller needs to tell the
 * difference between "the employee refused permission" and "the fix timed
 * out" so it can show a sensible message and route the day to HR.
 *
 * `enableHighAccuracy` is essential here. With it off, desktop browsers fall
 * back to IP geolocation, which is routinely kilometres out -- that would
 * make every punch INCONCLUSIVE and the whole geofence feature meaningless.
 *
 * `maximumAge: 0` deliberately refuses a cached fix. A five-minute-old
 * position is not evidence of where someone is standing now.
 */
export function getCurrentPosition(
  timeoutMs = 10000,
): Promise<PositionResult> {
  if (typeof navigator === "undefined" || !navigator.geolocation) {
    return Promise.resolve({ ok: false, reason: "unsupported" });
  }
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        resolve({
          ok: true,
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          gps_accuracy_m: pos.coords.accuracy,
        });
      },
      (err) => {
        if (err.code === err.PERMISSION_DENIED) {
          resolve({ ok: false, reason: "denied" });
        } else if (err.code === err.TIMEOUT) {
          resolve({ ok: false, reason: "timeout" });
        } else {
          resolve({ ok: false, reason: "unavailable" });
        }
      },
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 0 },
    );
  });
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