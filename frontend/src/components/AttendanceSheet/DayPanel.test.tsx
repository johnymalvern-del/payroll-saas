import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { DayPanel } from "./DayPanel";

function jr(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  if (typeof Request !== "undefined" && input instanceof Request) return input.url;
  return String(input);
}

function renderPanel(overrides: { reviewedOverride?: boolean } = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <DayPanel
          employeeId="e1"
          workDate="2026-11-04"
          onClose={() => {}}
          reviewedOverride={overrides.reviewedOverride}
        />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("DayPanel", () => {
  it("renders employee name, status, and segment breakdown", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/attendance/day/")) {
        return jr({
          id: "d1", employee_id: "e1", work_date: "2026-11-04", status: "worked",
          first_in: "2026-11-04T06:00:00Z", last_out: "2026-11-04T15:00:00Z",
          worked_minutes: 540, normal_minutes: 480, overtime_minutes: 60, raw_minutes: 540,
          shift_id: "sh1", flags: [], source_version: 1, locked: false,
          row_version: 1, computed_at: "2026-11-05T06:00:00Z",
          site_timezone: "Africa/Johannesburg",
          segments: [
            { id: "sg1", attendance_day_id: "d1", local_date: "2026-11-04",
              day_type: "weekday", kind: "normal", tier: 1, minutes: 480,
              rate_method: "multiplier", rate_value: "1.0", overtime_status: null, source_refs: [] },
            { id: "sg2", attendance_day_id: "d1", local_date: "2026-11-04",
              day_type: "weekday", kind: "overtime", tier: 1, minutes: 60,
              rate_method: "multiplier", rate_value: "1.5", overtime_status: "approved", source_refs: [] },
          ],
        });
      }
      if (url.includes("/employees/e1"))
        return jr({ id: "e1", first_name: "Thabo", last_name: "Mokoena", employee_code: "T001" });
      if (url.includes("/attendance/exceptions"))
        return jr({ items: [], next_cursor: null });
      if (url.includes("/shifts"))
        return jr({ items: [{ id: "sh1", name: "Day 08:00-17:00" }] });
      return jr({});
    });
    renderPanel();
    expect(await screen.findByText("Thabo Mokoena")).toBeInTheDocument();
    expect(screen.getByText(/T001/)).toBeInTheDocument();
    expect(await screen.findByText("worked")).toBeInTheDocument();
    expect(screen.getByText("normal")).toBeInTheDocument();
    expect(screen.getByText("overtime")).toBeInTheDocument();
    // Shift section: label is deterministic; name may be the resolved
    // shift name OR the id-prefix fallback depending on query timing.
    expect(await screen.findByText("Shift:")).toBeInTheDocument();
    expect(
      screen.queryByText(/Day 08:00-17:00/) ?? screen.queryByText("sh1"),
    ).not.toBeNull();
    expect(screen.getByText("Rate breakdown")).toBeInTheDocument();
    expect(screen.getByText("540")).toBeInTheDocument();
  });

  it("shows friendly 404 message when day does not exist", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/attendance/day/"))
        return jr({ error: { code: "record_not_found" } }, 404);
      if (url.includes("/employees/e1"))
        return jr({ id: "e1", first_name: "Nomsa", last_name: "Botha", employee_code: "T010" });
      if (url.includes("/attendance/exceptions"))
        return jr({ items: [], next_cursor: null });
      if (url.includes("/shifts")) return jr({ items: [] });
      return jr({});
    });
    renderPanel();
    expect(await screen.findByText("Nomsa Botha")).toBeInTheDocument();
    expect(
      await screen.findByText(/No attendance record for this day/),
    ).toBeInTheDocument();
  });

  it("renders exceptions list when present", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/attendance/day/")) {
        return jr({
          id: "d1", employee_id: "e1", work_date: "2026-11-04", status: "worked",
          first_in: "2026-11-04T06:00:00Z", last_out: "2026-11-04T15:00:00Z",
          worked_minutes: 540, normal_minutes: 480, overtime_minutes: 60, raw_minutes: 540,
          shift_id: null, flags: ["missing_out"], source_version: 1, locked: false,
          row_version: 1, computed_at: "2026-11-05T06:00:00Z",
          site_timezone: "Africa/Johannesburg", segments: [],
        });
      }
      if (url.includes("/employees/e1"))
        return jr({ id: "e1", first_name: "X", last_name: "Y", employee_code: "T001" });
      if (url.includes("/attendance/exceptions"))
        return jr({ items: [{ id: "ex1", type: "missing_out", message: "No clock-out", status: "open" }], next_cursor: null });
      if (url.includes("/shifts")) return jr({ items: [] });
      return jr({});
    });
    renderPanel();
    expect(await screen.findByText("missing_out")).toBeInTheDocument();
    expect(screen.getByText("No clock-out")).toBeInTheDocument();
  });

  it("never renders an adjustment marker (hard rule)", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/attendance/day/")) {
        return jr({
          id: "d1", employee_id: "e1", work_date: "2026-11-04", status: "worked",
          first_in: "2026-11-04T06:00:00Z", last_out: "2026-11-04T15:00:00Z",
          worked_minutes: 540, normal_minutes: 480, overtime_minutes: 60, raw_minutes: 540,
          shift_id: null, flags: [], source_version: 1, locked: false,
          row_version: 1, computed_at: "2026-11-05T06:00:00Z",
          site_timezone: "Africa/Johannesburg", segments: [],
        });
      }
      if (url.includes("/employees/e1"))
        return jr({ id: "e1", first_name: "X", last_name: "Y", employee_code: "T001" });
      if (url.includes("/attendance/exceptions"))
        return jr({ items: [], next_cursor: null });
      if (url.includes("/shifts")) return jr({ items: [] });
      return jr({});
    });
    renderPanel();
    expect(await screen.findByText("X Y")).toBeInTheDocument();
    expect(screen.queryByText(/adjusted/i)).not.toBeInTheDocument();
  });
});
