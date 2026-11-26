import type { PunchIn } from "../api/clockIn";

const STORAGE_KEY = "payroll.punch_queue.v1";

/**
 * How long a queued punch keeps its coordinates, measured from capture rather
 * than from the last sync attempt.
 *
 * A stale punch has both an unreliable location and a questionable time. Two
 * options were considered and one rejected:
 *
 *   submit without coordinates after expiry
 *     Every offline-expired punch would arrive as geofence_result="unavailable"
 *     and raise an "inconclusive" exception. That is the same exception type
 *     that flags a genuinely unverifiable location, and flooding it trains HR
 *     to dismiss it -- so the check stops working for the cases that matter.
 *
 *   drop the punch after expiry (chosen)
 *     A clock-in is lost. It surfaces to the employee as an expiry notice
 *     rather than disappearing, and HR sees an unexplained absence, which is a
 *     day-level exception rather than a per-punch one.
 *
 * Losing a punch is bad. Silently converting the location exception into noise
 * is worse, because it degrades a control that covers every punch, not just the
 * offline ones.
 */
export const QUEUE_TTL_MS = 24 * 60 * 60 * 1000;

/**
 * How many queued punches one flush attempts.
 *
 * A long backlog must not block the clock-in screen. Five per page load drains
 * a realistic backlog in a few visits while keeping the flush short.
 */
export const FLUSH_BATCH_SIZE = 5;

export type QueuedPunch = {
  /** The idempotency handle. Generated at capture so a retry cannot double-count. */
  client_punch_id: string;
  /** When the employee actually pressed clock-in, not when it was last tried. */
  captured_at: string;
  payload: PunchIn;
};

type StoredEntry = QueuedPunch & { ttl_ms: number };

function storageAvailable(): boolean {
  try {
    const probe = "__payroll_probe__";
    localStorage.setItem(probe, "1");
    localStorage.removeItem(probe);
    return true;
  } catch {
    return false;
  }
}

function readRaw(): StoredEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (e): e is StoredEntry =>
        typeof e === "object" &&
        e !== null &&
        typeof e.client_punch_id === "string" &&
        typeof e.captured_at === "string" &&
        typeof e.ttl_ms === "number" &&
        typeof e.payload === "object" &&
        e.payload !== null,
    );
  } catch {
    // Corrupt or unreadable storage is treated as empty rather than throwing.
    // A queue must never be the reason clock-in stops working.
    return [];
  }
}

function writeRaw(entries: StoredEntry[]): boolean {
  try {
    if (entries.length === 0) {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
    }
    return true;
  } catch {
    return false;
  }
}

function isExpired(entry: StoredEntry, now: number): boolean {
  const captured = Date.parse(entry.captured_at);
  if (Number.isNaN(captured)) return true;
  return now - captured > entry.ttl_ms;
}

/**
 * Drop expired entries and persist the survivors.
 *
 * Called on every read so an expired punch cannot sit in storage indefinitely
 * just because the app was never opened. Returns what was discarded so the
 * caller can tell the employee their clock-in expired.
 */
function pruneExpired(entries: StoredEntry[], now = Date.now()): {
  live: StoredEntry[];
  expired: StoredEntry[];
} {
  const live: StoredEntry[] = [];
  const expired: StoredEntry[] = [];
  for (const e of entries) {
    (isExpired(e, now) ? expired : live).push(e);
  }
  if (expired.length > 0) writeRaw(live);
  return { live, expired };
}

export function enqueuePunch(
  payload: PunchIn,
  capturedAt: Date = new Date(),
): { ok: boolean; expired: QueuedPunch[] } {
  const now = Date.now();
  const { live, expired } = pruneExpired(readRaw(), now);

  const entry: StoredEntry = {
    client_punch_id: payload.client_punch_id,
    captured_at: capturedAt.toISOString(),
    payload,
    ttl_ms: QUEUE_TTL_MS,
  };

  // The incoming entry is checked too, not only what is already stored. A
  // capture older than the TTL must never be written: it would be unreadable
  // the instant it went in, so the punch would vanish and the employee would
  // never learn their clock-in did not take.
  if (isExpired(entry, now)) {
    writeRaw(live);
    return { ok: true, expired: [...expired, entry].map(stripTtl) };
  }

  const next = [...live, entry];
  const ok = writeRaw(next);
  return { ok, expired: expired.map(stripTtl) };
}

export function queuedPunches(): QueuedPunch[] {
  const { live } = pruneExpired(readRaw());
  return live
    .map(stripTtl)
    .sort((a, b) => a.captured_at.localeCompare(b.captured_at));
}

export function queueSize(): number {
  return pruneExpired(readRaw()).live.length;
}

export function removeQueued(clientPunchId: string): void {
  const { live } = pruneExpired(readRaw());
  writeRaw(live.filter((e) => e.client_punch_id !== clientPunchId));
}

export function clearQueue(): void {
  writeRaw([]);
}

export function storageWorks(): boolean {
  return storageAvailable();
}

function stripTtl(e: StoredEntry): QueuedPunch {
  return {
    client_punch_id: e.client_punch_id,
    captured_at: e.captured_at,
    payload: e.payload,
  };
}