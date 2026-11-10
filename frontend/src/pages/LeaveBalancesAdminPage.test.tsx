import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor, within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const { mockPermsRef } = vi.hoisted(() => ({
  mockPermsRef: {
    value: ["leave_approve", "self_view"] as string[],
  },
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

import { LeaveBalancesAdminPage } from "./LeaveBalancesAdminPage";

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

function requestMethod(input: RequestInfo | URL): string {
  if (typeof Request !== "undefined" && input instanceof Request) return input.method;
  return "GET";
}

type Call = { url: string; method: string; body: string };

const EMP_ADA = {
  id: "e1",
  employee_code: "EMP001",
  first_name: "Ada",
  last_name: "Mokoena",
  status: "active",
};

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

const BAL = (
  id: string,
  employee_id: string,
  leave_type_id: string,
  available = "8.0000",
) => ({
  id,
  employee_id,
  leave_type_id,
  cycle_start: "2026-01-01",
  cycle_end: "2099-12-31",
  entitled: "20.0000",
  accrued: "10.0000",
  taken: "2.0000",
  pending: "0.0000",
  carried_in: "0.0000",
  adjusted: "0.0000",
  available,
  row_version: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

function setupMock(opts: {
  page1?: unknown[];
  page2?: unknown[];
  nextCursor?: string | null;
  stale?: boolean;
  asOf?: string | null;
  balancesStatus?: number;
  accrualStatus?: number;
  accrualBody?: unknown;
} = {}): { calls: Call[] } {
  const calls: Call[] = [];
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = requestUrl(input);
    const method = requestMethod(input);
    let body = "";
    if (
      method !== "GET" &&
      typeof Request !== "undefined" &&
      input instanceof Request
    ) {
      body = await input.clone().text();
    }
    calls.push({ url, method, body });

    if (method === "POST" && url.includes("/leave/accruals/run")) {
      return jr(
        opts.accrualBody ?? {
          employees_touched: 1,
          rows_written: 3,
          as_of: "2026-03-15",
        },
        opts.accrualStatus ?? 200,
      );
    }
    if (url.includes("/leave/balances")) {
      if (url.includes("cursor=")) {
        return jr({
          items: opts.page2 ?? [],
          next_cursor: null,
          accrued_as_of: opts.asOf ?? null,
          accrual_stale: opts.stale ?? false,
        });
      }
      return jr(
        {
          items: opts.page1 ?? [],
          next_cursor: opts.nextCursor ?? null,
          accrued_as_of: opts.asOf ?? null,
          accrual_stale: opts.stale ?? false,
        },
        opts.balancesStatus ?? 200,
      );
    }
    if (url.includes("/api/v1/employees")) {
      return jr({
        items: [EMP_ADA],
        next_cursor: null,
        total: 1,
      });
    }
    if (url.includes("/leave/types")) {
      return jr({ items: [TYPE_ANNUAL], next_cursor: null });
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
        <MemoryRouter initialEntries={["/leave/balances-admin"]}>
          <Routes>
            <Route
              path="/leave/balances-admin"
              element={<LeaveBalancesAdminPage />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

beforeEach(() => {
  mockPermsRef.value = ["leave_approve", "self_view"];
  vi.restoreAllMocks();
});
afterEach(() => { cleanup(); });

describe("LeaveBalancesAdminPage", () => {
  it("renders header and page when user has leave_approve", async () => {
    setupMock({});
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-balances-admin-page")).toBeInTheDocument(),
    );
    expect(screen.getByText("Leave Balances", { selector: "h2" })).toBeInTheDocument();
  });

  it("shows permission alert when user lacks leave_approve", async () => {
    mockPermsRef.value = ["self_view"];
    setupMock({});
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("balances-admin-no-permission"),
      ).toBeInTheDocument(),
    );
  });

  it("renders table with employee name and leave type", async () => {
    setupMock({ page1: [BAL("b1", "e1", "lt1")] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balances-admin-table")).toBeInTheDocument(),
    );
    const row = screen.getByTestId("balances-row-b1");
    expect(within(row).getByText(/Ada Mokoena/)).toBeInTheDocument();
    expect(within(row).getByText(/EMP001/)).toBeInTheDocument();
    expect(within(row).getByText("Annual Leave")).toBeInTheDocument();
    expect(within(row).getByText("8.00")).toBeInTheDocument();
  });

  it("shows empty state when no rows match", async () => {
    setupMock({ page1: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balances-admin-empty")).toBeInTheDocument(),
    );
  });

  it("shows error state on fetch failure", async () => {
    setupMock({ page1: [], balancesStatus: 500 });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balances-admin-error")).toBeInTheDocument(),
    );
  });

  it("shows accrual-stale banner when accrual_stale is true", async () => {
    setupMock({
      page1: [BAL("b1", "e1", "lt1")],
      stale: true,
      asOf: "2026-01-01T00:00:00Z",
    });
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("balances-accrual-stale"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId("balances-accrual-stale").textContent).toMatch(
      /not been run recently/i,
    );
  });

  it("cycle-from filter changes query param", async () => {
    const { calls } = setupMock({ page1: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balances-filter-from")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId("balances-filter-from"), {
      target: { value: "2026-01-01" },
    });
    await waitFor(() => {
      const reqs = calls.filter((c) => c.url.includes("/leave/balances"));
      expect(reqs.some((c) => c.url.includes("cycle_start_gte=2026-01-01"))).toBe(true);
    });
  });

  it("cycle-to filter changes query param", async () => {
    const { calls } = setupMock({ page1: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balances-filter-to")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId("balances-filter-to"), {
      target: { value: "2026-12-31" },
    });
    await waitFor(() => {
      const reqs = calls.filter((c) => c.url.includes("/leave/balances"));
      expect(reqs.some((c) => c.url.includes("cycle_start_lte=2026-12-31"))).toBe(true);
    });
  });

  it("Load more follows cursor and appends rows", async () => {
    const { calls } = setupMock({
      page1: [BAL("b1", "e1", "lt1")],
      page2: [BAL("b2", "e1", "lt1")],
      nextCursor: "abc",
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balances-row-b1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("balances-load-more"));
    await waitFor(() =>
      expect(screen.getByTestId("balances-row-b2")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("balances-row-b1")).toBeInTheDocument();
    expect(calls.filter((c) => c.url.includes("cursor=abc")).length).toBe(1);
  });

  it("Run accruals button hidden without user_manage", async () => {
    setupMock({ page1: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-balances-admin-page")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("balances-run-accruals")).toBeNull();
  });

  it("Run accruals button visible and POSTs when user has user_manage", async () => {
    mockPermsRef.value = ["leave_approve", "user_manage"];
    const { calls } = setupMock({ page1: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balances-run-accruals")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("balances-run-accruals"));
    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.includes("/leave/accruals/run"),
      );
      expect(post).toBeDefined();
    });
    await waitFor(() =>
      expect(screen.getByTestId("balances-action-msg").textContent).toMatch(
        /3 row\(s\) written/i,
      ),
    );
  });

  it("Row Adjust button opens the adjust modal", async () => {
    setupMock({ page1: [BAL("b1", "e1", "lt1")] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balances-row-b1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("balances-adjust-b1"));
    await waitFor(() =>
      expect(screen.getByTestId("adjust-balance-modal")).toBeInTheDocument(),
    );
  });

  it("passes employee_id when employee filter is used", async () => {
    const { calls } = setupMock({ page1: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balances-filter-employee")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("balances-filter-employee"));
    const option = await screen.findByRole("option", {
      name: /Ada Mokoena \(EMP001\)/,
    });
    fireEvent.click(option);
    await waitFor(() => {
      const reqs = calls.filter((c) => c.url.includes("/leave/balances"));
      expect(reqs.some((c) => c.url.includes("employee_id=e1"))).toBe(true);
    });
  });
});