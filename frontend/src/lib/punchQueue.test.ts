import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  QUEUE_TTL_MS,
  clearQueue,
  enqueuePunch,
  queueSize,
  queuedPunches,
  removeQueued,
} from "./punchQueue";
import type { PunchIn } from "../api/clockIn";

/**
 * Times are always relative to Date.now(). An earlier version used a hardcoded
 * calendar date, which worked on the day it was written and then silently
 * became "two days ago" -- three tests failed with empty queues that looked
 * like a TTL bug and were actually a test that had aged out.
 *
 * A TTL test must never contain an absolute date.
 */
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

function payload(id: string): PunchIn {
  return {
    client_punch_id: id,
    employee_id: "emp-1",
    device_time: new Date().toISOString(),
    device_now_at_send: new Date().toISOString(),
    method: "code",
    latitude: -33.9249,
    longitude: 18.4241,
    gps_accuracy_m: 5,
  };
}

/**
 * Replace localStorage with a stub for the duration of fn.
 *
 * A property spy on the real object was tried first and did not intercept:
 * writeRaw's setItem call succeeded and enqueuePunch returned ok=true. Whether
 * that is the environment's proxy trap or accessor definition is not worth
 * determining -- replacing the whole object tests the same contract without
 * depending on how Storage is implemented.
 */
function withLocalStorage<T>(stub: unknown, fn: () => T): T {
  const real = globalThis.localStorage;
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: stub,
  });
  try {
    return fn();
  } finally {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      writable: true,
      value: real,
    });
  }
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("punchQueue", () => {
  it("stores a punch with its coordinates", () => {
    enqueuePunch(payload("p1"));
    const q = queuedPunches();
    expect(q).toHaveLength(1);
    expect(q[0].payload.latitude).toBeCloseTo(-33.9249, 4);
    expect(q[0].client_punch_id).toBe("p1");
  });

  it("preserves the capture time, not the enqueue processing time", () => {
    const captured = new Date(Date.now() - MINUTE);
    enqueuePunch(payload("p1"), captured);
    expect(queuedPunches()[0].captured_at).toBe(captured.toISOString());
  });

  it("returns punches oldest first", () => {
    const newer = new Date(Date.now() - HOUR);
    const older = new Date(Date.now() - 2 * HOUR);
    enqueuePunch(payload("new"), newer);
    enqueuePunch(payload("old"), older);
    expect(queuedPunches().map((e) => e.client_punch_id)).toEqual(["old", "new"]);
  });

  it("removes a punch by its client id", () => {
    enqueuePunch(payload("p1"));
    enqueuePunch(payload("p2"));
    removeQueued("p1");
    expect(queuedPunches().map((e) => e.client_punch_id)).toEqual(["p2"]);
  });

  it("clears everything", () => {
    enqueuePunch(payload("p1"));
    enqueuePunch(payload("p2"));
    clearQueue();
    expect(queueSize()).toBe(0);
  });

  it("drops an entry older than the TTL and reports it", () => {
    const old = new Date(Date.now() - QUEUE_TTL_MS - MINUTE);
    const r = enqueuePunch(payload("stale"), old);
    expect(r.expired.map((e) => e.client_punch_id)).toEqual(["stale"]);
    expect(queuedPunches()).toHaveLength(0);
  });

  it("keeps an entry inside the TTL", () => {
    const recent = new Date(Date.now() - QUEUE_TTL_MS + MINUTE);
    enqueuePunch(payload("recent"), recent);
    expect(queuedPunches()).toHaveLength(1);
  });

  it("prunes an entry that expires while sitting in storage", () => {
    // Stored now, read after the TTL has elapsed. Pruning must happen on read,
    // not only on write, or an entry could sit indefinitely.
    vi.useFakeTimers();
    const t0 = new Date("2026-11-24T08:00:00Z");
    vi.setSystemTime(t0);
    enqueuePunch(payload("p1"), t0);
    expect(queueSize()).toBe(1);

    vi.setSystemTime(new Date(t0.getTime() + QUEUE_TTL_MS + MINUTE));
    expect(queuedPunches()).toHaveLength(0);
    expect(queueSize()).toBe(0);
  });

  it("treats corrupt storage as empty rather than throwing", () => {
    localStorage.setItem("payroll.punch_queue.v1", "{not json");
    expect(queuedPunches()).toEqual([]);
    enqueuePunch(payload("p1"));
    expect(queuedPunches()).toHaveLength(1);
  });

  it("discards entries with an unparseable capture time", () => {
    localStorage.setItem(
      "payroll.punch_queue.v1",
      JSON.stringify([
        {
          client_punch_id: "bad",
          captured_at: "not-a-date",
          payload: payload("bad"),
          ttl_ms: QUEUE_TTL_MS,
        },
      ]),
    );
    expect(queuedPunches()).toEqual([]);
  });

  it("ignores malformed array entries", () => {
    localStorage.setItem(
      "payroll.punch_queue.v1",
      JSON.stringify([{ nope: true }, null, "string"]),
    );
    expect(queuedPunches()).toEqual([]);
  });

  it("returns false instead of throwing when storage refuses a write", () => {
    // Storage that reads normally but throws on write: the realistic shape of
    // a full or private-browsing store. The whole object is replaced -- see
    // withLocalStorage for why a property spy was not enough.
    const r = withLocalStorage(
      {
        getItem: () => null,
        setItem: () => {
          throw new Error("QuotaExceededError");
        },
        removeItem: () => {},
        clear: () => {},
        key: () => null,
        length: 0,
      },
      () => enqueuePunch(payload("p1")),
    );

    expect(r.ok).toBe(false);
  });

  it("keeps working after a refused write", () => {
    // A failed enqueue must not poison the queue: the next attempt with
    // working storage should succeed.
    withLocalStorage(
      {
        getItem: () => null,
        setItem: () => {
          throw new Error("QuotaExceededError");
        },
        removeItem: () => {},
        clear: () => {},
        key: () => null,
        length: 0,
      },
      () => enqueuePunch(payload("p1")),
    );

    localStorage.clear();
    enqueuePunch(payload("p2"));
    expect(queuedPunches().map((e) => e.client_punch_id)).toEqual(["p2"]);
  });
});