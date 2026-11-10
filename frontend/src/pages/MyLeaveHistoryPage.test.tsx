import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor, within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../auth/useMe", () => ({
  useMe: () => ({
    data: {
      id: "u1",
      username: "test",
      role: "employee",
      employee_id: "e1",
      permissions: ["self_view", "self_submit"],
      must_change_password: false,
      default_timezone: null,
    },
    isLoading: false,
    isError: false,
    isSuccess: true,
  }),
}));

import { MyLeaveHistoryPage } from "./MyLeaveHistoryPage";

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

function requestMethod(input: RequestInfo | URL): string {
  if (typeof Request !== "undefined" && input instanceof Request) return input.method;
  return "GET";
}

type Call = { url: string; method: string; body: string };

function setupMock(opts: {
  types?: unknown[];
  firstPage?: unknown[];
  secondPage?: unknown[];
  firstCursor?: string | null;
  listStatus?: number;
}): { calls: Call[] } {
  const calls: Call[] = [];
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = requestUrl(input);
    const method = requestMethod(input);
    calls.push({ url, method, body: "" });

    if (url.includes("/leave/types")) {
      return jr({ items: opts.types ?? [], next_cursor: null });
    }
    if (url.includes("/leave/requests")) {
      if (url.includes("cursor=") && opts.secondPage) {
        return jr({ items: opts.secondPage, next_cursor: null });
      }
      return jr(
        {
          items: opts.firstPage ?? [],
          next_cursor: opts.firstCursor ?? null,
        },
        opts.listStatus ?? 200,
      );
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/leave/history"]}>
          <Routes>
            <Route path="/leave/history" element={<MyLeaveHistoryPage />} />
            <Route
              path="/leave/requests/:id"
              element={<div data-testid="detail-target">Detail</div>}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

const TYPE_ANNUAL = {
  id: "lt1",
  name: "Annual Leave",
  code: "ANNUAL",
  unit: "day",
  paid: true,
  accrual_method: "annual",
  accrual_amount: "21.0000",
  cycle: "calendar",
  requires_approval: true,
  requires_document_after_days: null,
  allow_negative: false,
  max_carryover: null,
  is_active: true,
  row_version: 1,
  approval_chain: ["manager", "hr"],
  requires_payroll_admin_final: false,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
};

const REQ = (id: string, status: string) => ({
  id,
  employee_id: "e1",
  leave_type_id: "lt1",
  from_date: "2026-03-10",
  to_date: "2026-03-14",
  days_requested: "5.00",
  reason: null,
  status,
  submitted_at: "2026-02-01T10:00:00Z",
  decided_at: null,
  decided_by_user_id: null,
  decision_note: null,
  row_version: 1,
  created_at: "2026-02-01T10:00:00Z",
  updated_at: "2026-02-01T10:00:00Z",
  captured_by_user_id: null,
  days: [],
  steps: [],
});

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("MyLeaveHistoryPage", () => {
  it("renders the page heading and back link", async () => {
    setupMock({ types: [TYPE_ANNUAL] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("my-leave-history-page")).toBeInTheDocument(),
    );
    expect(
      screen.getByText("My Leave History", { selector: "h2" }),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("my-leave-history-back-link"),
    ).toHaveAttribute("href", "/leave");
  });

  it("renders history rows with type name and status badge", async () => {
    setupMock({
      types: [TYPE_ANNUAL],
      firstPage: [REQ("r1", "submitted"), REQ("r2", "approved")],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("history-table")).toBeInTheDocument(),
    );
    const r1 = screen.getByTestId("history-row-r1");
    expect(within(r1).getByText("Annual Leave")).toBeInTheDocument();
    expect(within(r1).getByText("submitted")).toBeInTheDocument();
    const r2 = screen.getByTestId("history-row-r2");
    expect(within(r2).getByText("approved")).toBeInTheDocument();
  });

  it("shows empty state when no requests match", async () => {
    setupMock({ types: [TYPE_ANNUAL], firstPage: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("history-empty")).toBeInTheDocument(),
    );
  });

  it("shows error state when list fails", async () => {
    setupMock({ types: [TYPE_ANNUAL], listStatus: 500 });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("history-error")).toBeInTheDocument(),
    );
  });

  it("status filter changes the request query param", async () => {
    const { calls } = setupMock({ types: [TYPE_ANNUAL], firstPage: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("history-empty")).toBeInTheDocument(),
    );
    const initial = calls.filter((c) => c.url.includes("/leave/requests"));
    expect(initial[initial.length - 1].url).not.toContain("status=");

    fireEvent.click(screen.getByText("Approved"));
    await waitFor(() => {
      const updated = calls.filter((c) => c.url.includes("/leave/requests"));
      expect(updated[updated.length - 1].url).toContain("status=approved");
    });
  });

  it("load more follows next_cursor and appends rows", async () => {
    const { calls } = setupMock({
      types: [TYPE_ANNUAL],
      firstPage: [REQ("r1", "approved")],
      firstCursor: "abc",
      secondPage: [REQ("r2", "approved")],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("history-row-r1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("history-load-more"));
    await waitFor(() =>
      expect(screen.getByTestId("history-row-r2")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("history-row-r1")).toBeInTheDocument();
    const withCursor = calls.filter((c) => c.url.includes("cursor=abc"));
    expect(withCursor.length).toBe(1);
  });

  it("clicking a history row navigates to the detail page", async () => {
    setupMock({
      types: [TYPE_ANNUAL],
      firstPage: [REQ("r1", "approved")],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("history-row-r1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("history-row-r1"));
    await waitFor(() =>
      expect(screen.getByTestId("detail-target")).toBeInTheDocument(),
    );
  });
});