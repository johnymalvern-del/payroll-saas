import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { AttendanceSheetPage } from "./AttendanceSheetPage";

function jr(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  if (typeof Request !== "undefined" && input instanceof Request) return input.url;
  return String(input);
}

function setupMock(opts: {
  sheetItems?: unknown[];
  dailyItems?: unknown[];
  dayPayload?: unknown;
  markRefused?: unknown[];
}): void {
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = requestUrl(input);
    if (url.includes("/api/v1/attendance/sheet")) {
      return jr({ items: opts.sheetItems ?? [], next_cursor: null });
    }
    if (url.includes("/api/v1/attendance/daily")) {
      return jr({ items: opts.dailyItems ?? [], next_cursor: null });
    }
    if (url.includes("/api/v1/attendance/day/")) {
      return jr(opts.dayPayload ?? {});
    }
    if (url.includes("/api/v1/attendance/mark_reviewed")) {
      return jr({
        reviewed_count: 3,
        refused_days: opts.markRefused ?? [],
      });
    }
    if (
      url.includes("/api/v1/branches") ||
      url.includes("/api/v1/sites") ||
      url.includes("/api/v1/departments")
    ) {
      return jr({ items: [], next_cursor: null });
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <AttendanceSheetPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

const CELL = {
  work_date: "2025-06-01", status: "worked", worked_minutes: 480,
  normal_minutes: 480, overtime_minutes: 0, flags: [],
  open_exception_count: 0, locked: false, reviewed: false,
};
const EMPLOYEE = {
  employee_id: "e1", employee_code: "EMP001", employee_name: "Ada Lovelace",
  site_id: null, department_id: null, days: [CELL],
};
const DAY = {
  employee_id: "e1", employee_code: "EMP001", employee_name: "Ada Lovelace",
  work_date: "2025-06-01", status: "worked",
  first_in: "2025-06-01T08:00:00Z", last_out: "2025-06-01T16:30:00Z",
  worked_minutes: 480, normal_minutes: 480, overtime_minutes: 0,
  flags: [], open_exception_count: 0, locked: false, reviewed: false,
  punches: [
    { id: "p1", punch_time: "2025-06-01T08:00:00Z", direction: "in", source: "device", confidence: 0.9 },
    { id: "p2", punch_time: "2025-06-01T16:30:00Z", direction: "out", source: "device", confidence: 0.9 },
  ],
  exceptions: [],
};
const DAILY_ROW = {
  employee_id: "e1", employee_code: "EMP001", employee_name: "Ada Lovelace",
  work_date: "2025-06-01", status: "worked",
  first_in: "2025-06-01T08:00:00Z", last_out: "2025-06-01T16:30:00Z",
  worked_minutes: 480, normal_minutes: 480, overtime_minutes: 0,
  flags: [], open_exception_count: 0, locked: false, reviewed: false,
};

describe("AttendanceSheetPage monthly view", () => {
  beforeEach(() => setupMock({ sheetItems: [EMPLOYEE] }));

  it("renders title and employee row", async () => {
    renderPage();
    expect(screen.getByText("Attendance")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
      expect(screen.getByText("EMP001")).toBeInTheDocument();
    });
  });

  it("shows empty text when sheet returns no employees", async () => {
    setupMock({ sheetItems: [] });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/no employees match these filters/i)).toBeInTheDocument();
    });
  });

  it("renders a status badge for a worked cell", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("worked")).toBeInTheDocument();
    });
  });

  it("shows an error message when sheet fetch fails", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.includes("/api/v1/attendance/sheet")) {
        return jr({ error: { code: "boom" } }, 500);
      }
      return jr({ items: [], next_cursor: null });
    }) as unknown as typeof fetch;
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/could not load the attendance sheet/i)).toBeInTheDocument();
    });
  });

  it("opens the day panel on cell click and shows punches", async () => {
    setupMock({ sheetItems: [EMPLOYEE], dayPayload: DAY });
    renderPage();
    await waitFor(() => expect(screen.getByText("worked")).toBeInTheDocument());
    fireEvent.click(screen.getByText("worked"));
    await waitFor(() => {
      expect(screen.getByText("08:00:00")).toBeInTheDocument();
      expect(screen.getByText("16:30:00")).toBeInTheDocument();
    });
  });

  it("day panel never shows an adjustment marker (C2)", async () => {
    setupMock({ sheetItems: [EMPLOYEE], dayPayload: DAY });
    renderPage();
    await waitFor(() => expect(screen.getByText("worked")).toBeInTheDocument());
    fireEvent.click(screen.getByText("worked"));
    await waitFor(() => {
      expect(screen.getByText("08:00:00")).toBeInTheDocument();
    });
    const body = document.body.textContent ?? "";
    expect(/adjust/i.test(body)).toBe(false);
  });
});

describe("AttendanceSheetPage daily view", () => {
  beforeEach(() => setupMock({ dailyItems: [DAILY_ROW] }));

  it("switches to daily view and renders one row per employee", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("worked")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Daily"));
    await waitFor(() => {
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    });
  });
});

describe("AttendanceSheetPage mark reviewed", () => {
  it("shows refused days table when some days are refused", async () => {
    setupMock({
      sheetItems: [EMPLOYEE],
      markRefused: [
        { employee_id: "e1", employee_name: "Ada Lovelace", work_date: "2025-06-05", reason: "open_exceptions" },
      ],
    });
    renderPage();
    await waitFor(() => expect(screen.getByText("worked")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /mark clean days reviewed/i }));
    await waitFor(() => {
      expect(screen.getByText("open_exceptions")).toBeInTheDocument();
    });
  });
});
