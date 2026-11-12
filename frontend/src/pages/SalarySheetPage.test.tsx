import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor, within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const { mockPermsRef } = vi.hoisted(() => ({
  mockPermsRef: { value: ["payroll_preview"] as string[] },
}));

vi.mock("../auth/useMe", () => ({
  useMe: () => ({
    data: {
      id: "u-admin",
      username: "admin",
      role: "payroll_admin",
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

import { SalarySheetPage } from "./SalarySheetPage";

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

const PERIOD_ID = "pp-1";

const PERIOD = {
  id: PERIOD_ID,
  period_key: "2026-11",
  start_date: "2026-11-01",
  end_date: "2026-11-30",
  pay_date: "2026-11-30",
  status: "open",
  cutoff_at: "2026-11-25T17:00:00Z",
  row_version: 1,
};

function buildRow(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    employee_id: "e1",
    employee_code: "EMP001",
    employee_name: "Ada Mokoena",
    payslip_id: "ps-1",
    payslip_status: "preview",
    revision: 1,
    basic_earnings: "15000.00",
    additional_earnings: "500.00",
    gross: "15500.00",
    pre_tax_deductions: "1000.00",
    taxable_income: "14500.00",
    paye: "3000.00",
    uif_employee: "177.12",
    uif_employer: "177.12",
    sdl: "155.00",
    other_deductions: "200.00",
    reimbursements: "0.00",
    net: "11122.88",
    ...overrides,
  };
}

function buildSheet(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    pay_period_id: PERIOD_ID,
    pay_period_key: "2026-11",
    pay_period_status: "open",
    figures_state: "preview",
    run_id: "run-1",
    revision: 1,
    items: [buildRow()],
    next_cursor: null,
    ...overrides,
  };
}

function setupMock(opts: {
  period?: unknown;
  periodStatus?: number;
  sheet?: unknown;
  sheetStatus?: number;
} = {}): { calls: Call[] } {
  const calls: Call[] = [];
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = requestUrl(input);
    const method =
      typeof Request !== "undefined" && input instanceof Request
        ? input.method
        : "GET";
    calls.push({ url, method });
    if (url.includes(`/payroll/pay-periods/${PERIOD_ID}/salary-sheet`)) {
      return jr(
        opts.sheet ?? buildSheet(),
        opts.sheetStatus ?? 200,
      );
    }
    if (url.includes(`/payroll/pay-periods/${PERIOD_ID}`)) {
      return jr(opts.period ?? PERIOD, opts.periodStatus ?? 200);
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
        <MemoryRouter initialEntries={[`/payroll/pay-periods/${PERIOD_ID}/salary-sheet`]}>
          <Routes>
            <Route
              path="/payroll/pay-periods/:id/salary-sheet"
              element={<SalarySheetPage />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

beforeEach(() => {
  mockPermsRef.value = ["payroll_preview"];
  vi.restoreAllMocks();
});
afterEach(() => { cleanup(); });

describe("SalarySheetPage", () => {
  it("renders page header and period key", async () => {
    setupMock();
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("salary-sheet-page")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Salary Sheet/)).toBeInTheDocument();
    expect(screen.getByText(/2026-11/)).toBeInTheDocument();
  });

  it("calls salary-sheet endpoint with period id", async () => {
    const { calls } = setupMock();
    renderPage();
    await waitFor(() =>
      expect(
        calls.some((c) =>
          c.url.includes(`/payroll/pay-periods/${PERIOD_ID}/salary-sheet`),
        ),
      ).toBe(true),
    );
  });

  it("shows preview banner when figures_state=preview", async () => {
    setupMock();
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("salary-sheet-preview-banner"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("salary-sheet-finalised-banner"),
    ).toBeNull();
  });

  it("shows finalised banner when figures_state=finalised", async () => {
    setupMock({
      sheet: buildSheet({
        figures_state: "finalised",
        pay_period_status: "locked",
        items: [buildRow({ payslip_status: "current" })],
      }),
    });
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("salary-sheet-finalised-banner"),
      ).toBeInTheDocument(),
    );
  });

  it("shows no-preview message when figures_state=no_preview", async () => {
    setupMock({
      sheet: buildSheet({ figures_state: "no_preview", items: [] }),
    });
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("salary-sheet-no-preview"),
      ).toBeInTheDocument(),
    );
  });

  it("shows out-of-scope banner when figures_state=preview_out_of_scope", async () => {
    setupMock({
      sheet: buildSheet({
        figures_state: "preview_out_of_scope",
        items: [],
      }),
    });
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("salary-sheet-preview-out-of-scope"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("salary-sheet-preview-banner"),
    ).toBeNull();
    expect(
      screen.queryByTestId("salary-sheet-no-preview"),
    ).toBeNull();
    expect(
      screen.queryByTestId("salary-sheet-finalised-banner"),
    ).toBeNull();
  });

  it("renders one row per payslip with the canonical figures", async () => {
    setupMock();
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("salary-sheet-row-e1"),
      ).toBeInTheDocument(),
    );
    const row = screen.getByTestId("salary-sheet-row-e1");
    expect(within(row).getByText("Ada Mokoena")).toBeInTheDocument();
    expect(within(row).getByText("EMP001")).toBeInTheDocument();
    expect(within(row).getByText("15000.00")).toBeInTheDocument();
    expect(within(row).getByText("500.00")).toBeInTheDocument();
    expect(screen.getByTestId("salary-sheet-gross-e1").textContent).toBe(
      "15500.00",
    );
    expect(screen.getByTestId("salary-sheet-paye-e1").textContent).toBe(
      "3000.00",
    );
    expect(screen.getByTestId("salary-sheet-net-e1").textContent).toBe(
      "11122.88",
    );
  });

  it("search input updates query param after debounce", async () => {
    const { calls } = setupMock();
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("salary-sheet-search"),
      ).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId("salary-sheet-search"), {
      target: { value: "Mokoena" },
    });
    await waitFor(
      () => {
        const matching = calls.filter((c) =>
          c.url.includes("q=Mokoena"),
        );
        expect(matching.length).toBeGreaterThanOrEqual(1);
      },
      { timeout: 2000 },
    );
  });

  it("Export CSV button is disabled when no rows", async () => {
    setupMock({
      sheet: buildSheet({ figures_state: "no_preview", items: [] }),
    });
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("salary-sheet-export-csv"),
      ).toBeInTheDocument(),
    );
    expect(
      (screen.getByTestId("salary-sheet-export-csv") as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("Export CSV button is enabled when rows exist", async () => {
    setupMock();
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("salary-sheet-export-csv"),
      ).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(
        (screen.getByTestId("salary-sheet-export-csv") as HTMLButtonElement).disabled,
      ).toBe(false),
    );
  });

  it("fetch error shows an error state with a retry button", async () => {
    setupMock({ sheetStatus: 500 });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("salary-sheet-fetch-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("salary-sheet-retry")).toBeInTheDocument();
  });

  it("load more button appears when next_cursor is present", async () => {
    setupMock({
      sheet: buildSheet({ next_cursor: "next" }),
    });
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("salary-sheet-load-more"),
      ).toBeInTheDocument(),
    );
  });
});