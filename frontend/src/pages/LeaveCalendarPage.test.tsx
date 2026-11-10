import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor, within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import dayjs from "dayjs";

const { mockPermsRef } = vi.hoisted(() => ({
  mockPermsRef: { value: ["leave_approve"] as string[] },
}));

vi.mock("../auth/useMe", () => ({
  useMe: () => ({
    data: {
      id: "u-admin",
      username: "admin",
      role: "hr",
      employee_id: null,
      permissions: mockPermsRef.value,
      must_change_password: false,
      default_timezone: null,
    },
    isLoading: false,
    isError: false,
    isSuccess: true,
  }),
}));

import { LeaveCalendarPage } from "./LeaveCalendarPage";

if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {};
}

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

type Call = { url: string; method: string };

const EMP_ADA = { id: "e1", code: "EMP001", name: "Ada Mokoena" };
const EMP_SIPHO = { id: "e2", code: "EMP002", name: "Sipho Dlamini" };

function buildReq(opts: {
  id: string;
  emp_id: string;
  emp_name: string;
  emp_code: string;
  from: string;
  to: string;
  type_name?: string;
  status?: string;
}) {
  return {
    id: opts.id,
    employee_id: opts.emp_id,
    leave_type_id: "lt1",
    from_date: opts.from,
    to_date: opts.to,
    days_requested: "3.00",
    reason: null,
    status: opts.status ?? "approved",
    submitted_at: "2026-01-01T00:00:00Z",
    decided_at: "2026-01-01T00:00:00Z",
    decided_by_user_id: null,
    decision_note: null,
    row_version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    captured_by_user_id: null,
    days: [],
    steps: [],
    employee_code: opts.emp_code,
    employee_name: opts.emp_name,
    leave_type_name: opts.type_name ?? "Annual Leave",
  };
}

function setupMock(opts: {
  items?: unknown[];
  nextCursor?: string | null;
  status?: number;
} = {}): { calls: Call[] } {
  const calls: Call[] = [];
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = requestUrl(input);
    const method =
      typeof Request !== "undefined" && input instanceof Request
        ? input.method
        : "GET";
    calls.push({ url, method });
    if (url.includes("/leave/requests")) {
      return jr(
        {
          items: opts.items ?? [],
          next_cursor: opts.nextCursor ?? null,
        },
        opts.status ?? 200,
      );
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/leave/calendar"]}>
          <Routes>
            <Route path="/leave/calendar" element={<LeaveCalendarPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

beforeEach(() => {
  mockPermsRef.value = ["leave_approve"];
  vi.restoreAllMocks();
});
afterEach(() => { cleanup(); });

describe("LeaveCalendarPage", () => {
  it("renders header and month label for the current month", async () => {
    setupMock();
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-calendar-page")).toBeInTheDocument(),
    );
    expect(
      screen.getByText("Leave Calendar", { selector: "h2" }),
    ).toBeInTheDocument();
    const label = dayjs().startOf("month").format("MMMM YYYY");
    expect(screen.getByTestId("cal-month-label").textContent).toBe(label);
  });

  it("shows permission alert when user lacks leave_approve", async () => {
    mockPermsRef.value = ["self_view"];
    setupMock();
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("leave-calendar-no-permission"),
      ).toBeInTheDocument(),
    );
  });

  it("renders weekday headers Mon..Sun", async () => {
    setupMock();
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("cal-grid")).toBeInTheDocument(),
    );
    const grid = screen.getByTestId("cal-grid");
    for (const w of ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]) {
      expect(within(grid).getByText(w)).toBeInTheDocument();
    }
  });

  it("fetches with status=approved and window bounds", async () => {
    const { calls } = setupMock();
    renderPage();
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("/leave/requests"))).toBe(true),
    );
    const reqCall = calls.find((c) => c.url.includes("/leave/requests"))!;
    expect(reqCall.url).toContain("status=approved");
    expect(reqCall.url).toContain("from_date_gte=");
    expect(reqCall.url).toContain("to_date_lte=");
  });

  it("renders one chip per covered calendar day for a 5-day leave", async () => {
    const now = dayjs().startOf("month");
    const from = now.add(9, "day").format("YYYY-MM-DD");
    const to = now.add(13, "day").format("YYYY-MM-DD");
    setupMock({
      items: [
        buildReq({
          id: "r1",
          emp_id: EMP_ADA.id,
          emp_name: EMP_ADA.name,
          emp_code: EMP_ADA.code,
          from,
          to,
        }),
      ],
    });
    renderPage();
    // Wait on the chip itself — the grid renders synchronously before the
    // query resolves, so waiting on the grid would race.
    await waitFor(() =>
      expect(screen.getAllByTestId("cal-chip-r1").length).toBe(5),
    );
  });

  it("clicking an empty day opens drawer with 'no approved leave' message", async () => {
    setupMock();
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("cal-grid")).toBeInTheDocument(),
    );
    const first = dayjs().startOf("month").format("YYYY-MM-DD");
    fireEvent.click(screen.getByTestId(`cal-cell-${first}`));
    await waitFor(() =>
      expect(screen.getByTestId("cal-day-drawer-empty")).toBeInTheDocument(),
    );
  });

  it("clicking a day with leave opens drawer with details", async () => {
    const now = dayjs().startOf("month");
    const from = now.add(9, "day").format("YYYY-MM-DD");
    const to = now.add(9, "day").format("YYYY-MM-DD");
    setupMock({
      items: [
        buildReq({
          id: "r1",
          emp_id: EMP_ADA.id,
          emp_name: EMP_ADA.name,
          emp_code: EMP_ADA.code,
          from,
          to,
        }),
      ],
    });
    renderPage();
    // Wait for the chip to appear before clicking the cell, so the drawer
    // has data to render.
    await waitFor(() =>
      expect(screen.getByTestId("cal-chip-r1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId(`cal-cell-${from}`));
    await waitFor(() =>
      expect(screen.getByTestId("cal-detail-r1")).toBeInTheDocument(),
    );
    const detail = screen.getByTestId("cal-detail-r1");
    expect(within(detail).getByText(/Ada Mokoena/)).toBeInTheDocument();
    expect(within(detail).getByText("Annual Leave")).toBeInTheDocument();
  });

  it("prev button re-fetches with earlier window bounds", async () => {
    const { calls } = setupMock();
    renderPage();
    await waitFor(() =>
      expect(
        calls.filter((c) => c.url.includes("/leave/requests")).length,
      ).toBe(1),
    );
    const firstUrl = calls.find((c) =>
      c.url.includes("/leave/requests"),
    )!.url;
    const firstFrom = new URL(firstUrl).searchParams.get("from_date_gte")!;
    fireEvent.click(screen.getByTestId("cal-prev"));
    await waitFor(() =>
      expect(
        calls.filter((c) => c.url.includes("/leave/requests")).length,
      ).toBe(2),
    );
    const reqCalls = calls.filter((c) => c.url.includes("/leave/requests"));
    const secondFrom = new URL(reqCalls[1].url).searchParams.get(
      "from_date_gte",
    )!;
    expect(secondFrom < firstFrom).toBe(true);
  });

  it("next button advances the month label", async () => {
    setupMock();
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("cal-month-label")).toBeInTheDocument(),
    );
    const initial = screen.getByTestId("cal-month-label").textContent;
    fireEvent.click(screen.getByTestId("cal-next"));
    const nextMonth = dayjs()
      .startOf("month")
      .add(1, "month")
      .format("MMMM YYYY");
    await waitFor(() =>
      expect(screen.getByTestId("cal-month-label").textContent).toBe(
        nextMonth,
      ),
    );
    expect(screen.getByTestId("cal-month-label").textContent).not.toBe(
      initial,
    );
  });

  it("today button returns to current month", async () => {
    setupMock();
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("cal-month-label")).toBeInTheDocument(),
    );
    const todayLabel = dayjs().startOf("month").format("MMMM YYYY");
    fireEvent.click(screen.getByTestId("cal-next"));
    await waitFor(() =>
      expect(screen.getByTestId("cal-month-label").textContent).not.toBe(
        todayLabel,
      ),
    );
    fireEvent.click(screen.getByTestId("cal-today"));
    await waitFor(() =>
      expect(screen.getByTestId("cal-month-label").textContent).toBe(
        todayLabel,
      ),
    );
  });

  it("error state on fetch failure", async () => {
    setupMock({ status: 500 });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("cal-error")).toBeInTheDocument(),
    );
  });

  it("truncation alert shown when next_cursor is present", async () => {
    setupMock({ nextCursor: "more" });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("cal-truncated")).toBeInTheDocument(),
    );
  });

  it("multiple employees on the same day render multiple chips", async () => {
    const now = dayjs().startOf("month");
    const d = now.add(9, "day").format("YYYY-MM-DD");
    setupMock({
      items: [
        buildReq({
          id: "r1",
          emp_id: EMP_ADA.id,
          emp_name: EMP_ADA.name,
          emp_code: EMP_ADA.code,
          from: d,
          to: d,
        }),
        buildReq({
          id: "r2",
          emp_id: EMP_SIPHO.id,
          emp_name: EMP_SIPHO.name,
          emp_code: EMP_SIPHO.code,
          from: d,
          to: d,
        }),
      ],
    });
    renderPage();
    // Wait on the chips themselves (data-dependent), not on the cell
    // container (which renders synchronously).
    await waitFor(() => {
      const cell = screen.getByTestId(`cal-cell-${d}`);
      expect(within(cell).getByTestId("cal-chip-r1")).toBeInTheDocument();
      expect(within(cell).getByTestId("cal-chip-r2")).toBeInTheDocument();
    });
  });
});