import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { PayslipSoFarPage } from "./PayslipSoFarPage";

function jr(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  if (input instanceof Request) return input.url;
  return String(input);
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <MemoryRouter
          initialEntries={["/payroll/pay-periods/p1/payslip-so-far/e1"]}
        >
          <Routes>
            <Route
              path="/payroll/pay-periods/:id/payslip-so-far/:employeeId"
              element={<PayslipSoFarPage />}
            />
          </Routes>
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const PERIOD = {
  id: "p1",
  period_key: "2026-11",
  start_date: "2026-11-01",
  end_date: "2026-11-30",
  pay_date: "2026-12-05",
  status: "open",
  cutoff_at: "2026-12-01T00:00:00Z",
  row_version: 1,
};

function baseEstimate(overrides: Record<string, unknown> = {}) {
  return {
    employee_id: "e1",
    employee_code: "T001",
    employee_name: "Thabo Mokoena",
    pay_period_id: "p1",
    revision: null,
    status: "as_of",
    as_of: "2026-11-05",
    available: true,
    reason_unavailable: null,
    gross: "2400.00",
    paye: "400.00",
    net: "1950.00",
    warnings: [],
    lines: [
      {
        earning_type_code: "normal_hours",
        earning_type_name: "Normal hours (480 min)",
        rate_source: "attendance",
        amount: "2400.00",
        minutes: 480,
      },
    ],
    deductions: [
      {
        deduction_type_code: "uif",
        deduction_type_name: "UIF",
        amount: "50.00",
      },
    ],
    unacknowledged_formulas: [],
    demo_values: false,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PayslipSoFarPage", () => {
  it("always shows the ESTIMATE banner", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/preview/")) return jr(baseEstimate());
      return jr(PERIOD);
    });
    renderPage();
    expect(
      await screen.findByTestId("payslip-estimate-banner"),
    ).toBeInTheDocument();
    expect(screen.getByText(/not a payslip/i)).toBeInTheDocument();
  });

  it("shows demo values banner when demo_values true", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/preview/"))
        return jr(baseEstimate({ demo_values: true }));
      return jr(PERIOD);
    });
    renderPage();
    expect(
      await screen.findByTestId("payslip-demo-banner"),
    ).toBeInTheDocument();
  });

  it("shows unacknowledged formulas banner when list non-empty", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/preview/"))
        return jr(
          baseEstimate({ unacknowledged_formulas: ["f1", "f2"] }),
        );
      return jr(PERIOD);
    });
    renderPage();
    expect(
      await screen.findByTestId("payslip-formulas-banner"),
    ).toBeInTheDocument();
    expect(screen.getByText(/2 payroll formula/i)).toBeInTheDocument();
  });

  it("shows as_of date prominently", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/preview/")) return jr(baseEstimate());
      return jr(PERIOD);
    });
    renderPage();
    expect(
      await screen.findByTestId("payslip-asof-label"),
    ).toBeInTheDocument();
    expect(screen.getByText(/so far, up to/i)).toBeInTheDocument();
  });

  it("renders lines table and Gross/PAYE/Net cards", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/preview/")) return jr(baseEstimate());
      return jr(PERIOD);
    });
    renderPage();
    expect(
      await screen.findByTestId("payslip-lines-table"),
    ).toBeInTheDocument();
    expect(screen.getByText("Normal hours (480 min)")).toBeInTheDocument();
    expect(screen.getByTestId("payslip-gross")).toHaveTextContent("2400.00");
    expect(screen.getByTestId("payslip-paye")).toHaveTextContent("400.00");
    expect(screen.getByTestId("payslip-net")).toHaveTextContent("1950.00");
  });

  it("renders deductions table", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/preview/")) return jr(baseEstimate());
      return jr(PERIOD);
    });
    renderPage();
    expect(
      await screen.findByTestId("payslip-deductions-table"),
    ).toBeInTheDocument();
    expect(screen.getByText("UIF")).toBeInTheDocument();
  });

  it("shows monthly refusal card and no numeric output", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/preview/"))
        return jr(
          baseEstimate({
            available: false,
            reason_unavailable: "monthly_proration_pending",
            gross: null,
            paye: null,
            net: null,
            lines: [],
            deductions: [],
          }),
        );
      return jr(PERIOD);
    });
    renderPage();
    expect(
      await screen.findByTestId("payslip-monthly-refusal"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not available for monthly salary/i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("payslip-gross")).not.toBeInTheDocument();
  });

  it("date picker fires new fetch when changed", async () => {
    const calls: string[] = [];
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      calls.push(url);
      if (url.includes("/preview/")) return jr(baseEstimate());
      return jr(PERIOD);
    });
    renderPage();
    const input = await screen.findByTestId("payslip-asof-input");
    fireEvent.change(input, { target: { value: "2026-11-02" } });
    await waitFor(
      () => {
        const previews = calls.filter((u) => u.includes("/preview/"));
        expect(previews.some((u) => u.includes("as_of=2026-11-02"))).toBe(true);
      },
      { timeout: 1500 },
    );
  });

  it("shows permission error when 403", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/preview/"))
        return jr({ error: { code: "forbidden", message: "Forbidden" } }, 403);
      return jr(PERIOD);
    });
    renderPage();
    expect(
      await screen.findByTestId("payslip-error"),
    ).toHaveTextContent(/permission/i);
  });
});
