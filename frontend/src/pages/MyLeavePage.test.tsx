import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor, within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter } from "react-router-dom";

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

import { MyLeavePage } from "./MyLeavePage";

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

function setupMock(opts: {
  types?: unknown[];
  balances?: unknown[];
  recent?: unknown[];
  accrualStale?: boolean;
  balancesStatus?: number;
  recentStatus?: number;
  typesStatus?: number;
}): { calls: Call[] } {
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

    if (url.includes("/leave/types")) {
      return jr(
        { items: opts.types ?? [], next_cursor: null },
        opts.typesStatus ?? 200,
      );
    }
    if (url.includes("/leave/balances")) {
      return jr(
        {
          items: opts.balances ?? [],
          next_cursor: null,
          accrued_as_of: null,
          accrual_stale: opts.accrualStale ?? false,
        },
        opts.balancesStatus ?? 200,
      );
    }
    if (url.includes("/leave/requests")) {
      return jr(
        { items: opts.recent ?? [], next_cursor: null },
        opts.recentStatus ?? 200,
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
        <MemoryRouter>
          <MyLeavePage />
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

const TYPE_SICK = {
  ...TYPE_ANNUAL,
  id: "lt2",
  name: "Sick Leave",
  code: "SICK",
  accrual_amount: "30.0000",
};

const BAL_ANNUAL = {
  id: "b1",
  employee_id: "e1",
  leave_type_id: "lt1",
  cycle_start: "2026-01-01",
  cycle_end: "2026-12-31",
  entitled: "21.0000",
  accrued: "17.5000",
  taken: "5.0000",
  pending: "0.5000",
  carried_in: "0.0000",
  adjusted: "0.0000",
  available: "12.0000",
  row_version: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const BAL_SICK = {
  ...BAL_ANNUAL,
  id: "b2",
  leave_type_id: "lt2",
  entitled: "30.0000",
  accrued: "25.0000",
  taken: "0.0000",
  pending: "0.0000",
  available: "25.0000",
};

const REQ_RECENT = {
  id: "r1",
  employee_id: "e1",
  leave_type_id: "lt1",
  from_date: "2026-03-10",
  to_date: "2026-03-14",
  days_requested: "5.00",
  reason: null,
  status: "submitted",
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
};

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("MyLeavePage", () => {
  it("renders the dashboard title and Apply button", async () => {
    setupMock({});
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("my-leave-page")).toBeInTheDocument(),
    );
    expect(screen.getByText("My Leave", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByTestId("my-leave-apply-button")).toBeInTheDocument();
    expect(screen.getByTestId("my-leave-history-link")).toBeInTheDocument();
  });

  it("renders balance cards with available and entitled values", async () => {
    setupMock({
      types: [TYPE_ANNUAL, TYPE_SICK],
      balances: [BAL_ANNUAL, BAL_SICK],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balance-card-lt1")).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("balance-available-lt1"),
    ).toHaveTextContent("12.00");
    expect(screen.getByTestId("balance-card-lt1")).toHaveTextContent(
      /Entitled 21\.00/,
    );
    expect(screen.getByTestId("balance-card-lt2")).toHaveTextContent(
      /Sick Leave/,
    );
  });

  it("shows the accrual-stale warning when applicable", async () => {
    setupMock({
      types: [TYPE_ANNUAL],
      balances: [BAL_ANNUAL],
      accrualStale: true,
    });
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("my-leave-accrual-stale"),
      ).toBeInTheDocument(),
    );
  });

  it("does not show the accrual-stale warning when fresh", async () => {
    setupMock({
      types: [TYPE_ANNUAL],
      balances: [BAL_ANNUAL],
      accrualStale: false,
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balance-card-lt1")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("my-leave-accrual-stale")).toBeNull();
  });

  it("shows empty balance state", async () => {
    setupMock({ types: [TYPE_ANNUAL], balances: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balances-empty")).toBeInTheDocument(),
    );
  });

  it("shows empty recent applications state", async () => {
    setupMock({ types: [TYPE_ANNUAL], balances: [BAL_ANNUAL], recent: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("recent-empty")).toBeInTheDocument(),
    );
  });

  it("renders recent requests table with status badge", async () => {
    setupMock({
      types: [TYPE_ANNUAL],
      balances: [BAL_ANNUAL],
      recent: [REQ_RECENT],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("recent-table")).toBeInTheDocument(),
    );
    const row = screen.getByTestId("recent-row-r1");
    expect(within(row).getByText("Annual Leave")).toBeInTheDocument();
    expect(within(row).getByText("submitted")).toBeInTheDocument();
    expect(within(row).getByText("5.00")).toBeInTheDocument();
  });

  it("shows balances error state", async () => {
    setupMock({
      types: [TYPE_ANNUAL],
      balancesStatus: 500,
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("balances-error")).toBeInTheDocument(),
    );
  });

  it("shows recent error state", async () => {
    setupMock({
      types: [TYPE_ANNUAL],
      balances: [BAL_ANNUAL],
      recentStatus: 500,
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("recent-error")).toBeInTheDocument(),
    );
  });

  it("opens the Apply modal on button click", async () => {
    setupMock({ types: [TYPE_ANNUAL], balances: [BAL_ANNUAL] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("my-leave-apply-button")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("my-leave-apply-button"));
    await waitFor(() =>
      expect(screen.getByTestId("apply-leave-type")).toBeInTheDocument(),
    );
  });
});