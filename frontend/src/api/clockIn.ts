import { getAccessToken } from "./client";
import { getTenantSlug } from "./tenant";

const BASE = "/api/v1";

/**
 * An API error carrying the server's machine-readable code.
 *
 * The clock-in page needs to distinguish "no PIN set" from "PIN locked" and
 * show different guidance for each, and the human message alone is not a
 * contract. `code` is the server's, unchanged.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

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
  /**
   * "code" = employee code plus a photograph, no verification.
   * "pin"  = employee code plus a 6-digit PIN, verified server-side.
   *
   * The PIN path is the non-biometric alternative section 4 of the privacy
   * policy requires. It performs real verification; "code" does not.
   */
  method: string;
  photo_base64?: string | null;
  match_score?: number | string | null;
  liveness_passed?: boolean | null;
  latitude?: number | string | null;
  longitude?: number | string | null;
  gps_accuracy_m?: number | string | null;
  /** Required only when method is "pin". Never stored or logged server-side. */
  pin?: string | null;
};

export type PunchLocationOut = {
  latitude: string;
  longitude: string;
  gps_accuracy_m?: string | null;
  distance_m?: string | null;
  captured_at: string;
};

export type PunchOut = {
  id: string;
  effective_time: string;
  status: string;
  flags: string[];
  method?: string;
  site_id?: string | null;
  site_name?: string | null;
  geofence_result?: string | null;
  geofence_reason?: string | null;
  distance_band?: string | null;
  location?: PunchLocationOut | null;
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

/** Turn a failed response into an ApiError carrying the server's code. */
async function toApiError(res: Response): Promise<ApiError> {
  const body = await res.json().catch(() => ({}));
  const err = (body as { error?: { code?: string; message?: string } })?.error;
  return new ApiError(
    err?.code ?? "request_failed",
    err?.message ?? `HTTP ${res.status}`,
    res.status,
  );
}

export async function resolveEmployeeByCode(
  code: string,
): Promise<EmployeeLookup | null> {
  const url =
    `${BASE}/employees?employee_code=${encodeURIComponent(code)}&limit=2`;
  const res = await fetch(url, { credentials: "include", headers: baseHeaders() });
  if (!res.ok) {
    throw await toApiError(res);
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
    throw await toApiError(res);
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