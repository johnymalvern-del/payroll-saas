import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor, within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import {
  MemoryRouter, Route, Routes, useLocation,
} from "react-router-dom";

const { mockPermsRef } = vi.hoisted(() => ({
  mockPermsRef: { value: ["employee_crud", "self_view", "leave_approve"] as string[] },
}));

vi.mock("../auth/useMe", () => ({
  useMe: () => ({
    data: {
      id: "u-hr",
      username: "hr_user",
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

import { LeaveAdminPage } from "./LeaveAdminPage";

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
  employees?: unknown[];
  branches?: unknown[];
  leaveTypes?: unknown[];
  requestsPage1?: unknown[];
  requestsPage2?: unknown[];
  nextCursor?: string | null;
  requestsStatus?: number;
}): { calls: Call[] } {
  const calls: Call[] = [];
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = requestUrl(input);
    const method = requestMethod(input);
    calls.push({ url, method, body: "" });

    if (url.includes("/api/v1/employees")) {
      return jr({
        items: opts.employees ?? [],
        next_cursor: null,
        total: null,
      });
    }
    if (url.includes("/api/v1/branches")) {
      return jr({
        items: opts.branches ?? [],
        next_cursor: null,
      });
    }
    if (url.includes("/leave/types")) {
      return jr({ items: opts.leaveTypes ?? [], next_cursor: null });
    }
    if (url.includes("/leave/requests")) {
      if (url.includes("cursor=")) {
        return jr({
          items: opts.requestsPage2 ?? [],
          next_cursor: null,
        });
      }
      return jr(
        {
          items: opts.requestsPage1 ?? [],
          next_cursor: opts.nextCursor ?? null,
        },
        opts.requestsStatus ?? 200,
      );
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function DetailStub() {
  const loc = useLocation();
  return (
    <div data-testid="detail-target">
      {JSON.stringify(loc.state)}
    </div>
  );
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/leave/admin"]}>
          <Routes>
            <Route path="/leave/admin" element={<LeaveAdminPage />} />
            <Route path="/leave/requests/:id" element={<DetailStub />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

const EMP_ADA = {
  id: "e1",
  employee_code: "EMP001",
  first_name: "Ada",
  last_name: "Mokoena",
  national_id_masked: null,
  email: null,
  mobile: null,
  date_of_birth: null,
  hire_date: "2024-01-15",
  termination_date: null,
  status: "active",
  job_title: null,
  branch_id: "b1",
  site_id: null,
  department_id: null,
  manager_id: null,
  employee_type: "hourly",
  pay_basis: "hourly",
  pay_frequency: "monthly",
  base_rate: null,
  overtime_eligible: true,
  clocks: true,
  work_pattern_id: null,
  default_shift_id: null,
  bank_name: null,
  bank_account_number_masked: null,
  bank_branch_code: null,
  account_type: null,
  tax_number: null,
  medical_aid_dependants: 0,
  retirement_fund_flags: null,
  uif_exempt: false,
  notes: null,
  row_version: 1,
};

const EMP_SIPHO = {
  ...EMP_ADA,
  id: "e2",
  employee_code: "EMP002",
  first_name: "Sipho",
  last_name: "Dlamini",
  branch_id: "b2",
};

const BRANCH_HQ = {
  id: "b1",
  name: "Head Office",
  code: "HQ",
  address: null,
  is_active: true,
  row_version: 1,
};

const BRANCH_COASTAL = {
  id: "b2",
  name: "Coastal",
  code: "CO",
  address: null,
  is_active: true,
  row_version: 1,
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

const TYPE_SICK = {
  ...TYPE_ANNUAL,
  id: "lt2",
  name: "Sick Leave",
  code: "SICK",
};

const REQ = (
  id: string,
  employee_id: string,
  status: string,
  leave_type_id = "lt1",
) => ({
  id,
  employee_id,
  leave_type_id,
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

beforeEach(() => {
  mockPermsRef.value = ["employee_crud", "self_view", "leave_approve"];
  vi.restoreAllMocks();
});
afterEach(() => { cleanup(); });

describe("LeaveAdminPage", () => {
  it("renders page header and My Leave link", async () => {
    setupMock({
      employees: [EMP_ADA],
      branches: [BRANCH_HQ],
      leaveTypes: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-page")).toBeInTheDocument(),
    );
    expect(screen.getByText("Leave Admin", { selector: "h2" })).toBeInTheDocument();
    expect(
      screen.getByTestId("leave-admin-my-leave-link"),
    ).toHaveAttribute("href", "/leave");
  });

  it("shows permission alert when user lacks employee_crud", async () => {
    mockPermsRef.value = ["self_view"];
    setupMock({});
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("leave-admin-no-permission"),
      ).toBeInTheDocument(),
    );
  });

  it("renders table with employee name and leave type resolved", async () => {
    setupMock({
      employees: [EMP_ADA],
      branches: [BRANCH_HQ],
      leaveTypes: [TYPE_ANNUAL],
      requestsPage1: [REQ("r1", "e1", "submitted")],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-table")).toBeInTheDocument(),
    );
    const row = screen.getByTestId("leave-admin-row-r1");
    expect(within(row).getByText(/Ada Mokoena/)).toBeInTheDocument();
    expect(within(row).getByText(/EMP001/)).toBeInTheDocument();
    expect(within(row).getByText("Annual Leave")).toBeInTheDocument();
    expect(within(row).getByText("submitted")).toBeInTheDocument();
    expect(within(row).getByText("5.00")).toBeInTheDocument();
  });

  it("shows empty state when no requests match", async () => {
    setupMock({
      employees: [EMP_ADA],
      branches: [BRANCH_HQ],
      leaveTypes: [TYPE_ANNUAL],
      requestsPage1: [],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-empty")).toBeInTheDocument(),
    );
  });

  it("shows error state when requests fail", async () => {
    setupMock({
      employees: [EMP_ADA],
      branches: [BRANCH_HQ],
      leaveTypes: [TYPE_ANNUAL],
      requestsPage1: [],
      requestsStatus: 500,
    });
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("leave-admin-requests-error"),
      ).toBeInTheDocument(),
    );
  });

  it("status filter changes native query param", async () => {
    const { calls } = setupMock({
      employees: [EMP_ADA],
      branches: [BRANCH_HQ],
      leaveTypes: [TYPE_ANNUAL],
      requestsPage1: [],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-page")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByText("Approved"));
    await waitFor(() => {
      const reqs = calls.filter((c) => c.url.includes("/leave/requests"));
      expect(
        reqs.some((c) => c.url.includes("status=approved")),
      ).toBe(true);
    });
  });

  it("employee filter changes native query param", async () => {
    const { calls } = setupMock({
      employees: [EMP_ADA, EMP_SIPHO],
      branches: [BRANCH_HQ, BRANCH_COASTAL],
      leaveTypes: [TYPE_ANNUAL],
      requestsPage1: [],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-employee-filter")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-admin-employee-filter"));
    const option = await screen.findByText(/EMP002 — Sipho Dlamini/);
    fireEvent.click(option);
    await waitFor(() => {
      const reqs = calls.filter((c) => c.url.includes("/leave/requests"));
      expect(
        reqs.some((c) => c.url.includes("employee_id=e2")),
      ).toBe(true);
    });
  });

  it("date filters change native query params", async () => {
    const { calls } = setupMock({
      employees: [EMP_ADA],
      branches: [BRANCH_HQ],
      leaveTypes: [TYPE_ANNUAL],
      requestsPage1: [],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-from-date")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId("leave-admin-from-date"), {
      target: { value: "2026-03-01" },
    });
    fireEvent.change(screen.getByTestId("leave-admin-to-date"), {
      target: { value: "2026-03-31" },
    });
    await waitFor(() => {
      const reqs = calls.filter((c) => c.url.includes("/leave/requests"));
      const withFrom = reqs.some((c) => c.url.includes("from_date_gte=2026-03-01"));
      const withTo = reqs.some((c) => c.url.includes("to_date_lte=2026-03-31"));
      expect(withFrom).toBe(true);
      expect(withTo).toBe(true);
    });
  });

  it("branch filter hides non-matching loaded rows", async () => {
    setupMock({
      employees: [EMP_ADA, EMP_SIPHO],
      branches: [BRANCH_HQ, BRANCH_COASTAL],
      leaveTypes: [TYPE_ANNUAL],
      requestsPage1: [
        REQ("r1", "e1", "submitted"),
        REQ("r2", "e2", "submitted"),
      ],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-row-r1")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("leave-admin-row-r2")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("leave-admin-branch-filter"));
    const hq = await screen.findByText("Head Office");
    fireEvent.click(hq);
    await waitFor(() => {
      expect(screen.getByTestId("leave-admin-row-r1")).toBeInTheDocument();
      expect(screen.queryByTestId("leave-admin-row-r2")).toBeNull();
    });
  });

  it("leave type filter hides non-matching loaded rows", async () => {
    setupMock({
      employees: [EMP_ADA],
      branches: [BRANCH_HQ],
      leaveTypes: [TYPE_ANNUAL, TYPE_SICK],
      requestsPage1: [
        REQ("r1", "e1", "submitted", "lt1"),
        REQ("r2", "e1", "submitted", "lt2"),
      ],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-row-r1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-admin-leave-type-filter"));
    const sick = await screen.findByRole("option", { name: "Sick Leave" });
    fireEvent.click(sick);
    await waitFor(() => {
      expect(screen.getByTestId("leave-admin-row-r2")).toBeInTheDocument();
      expect(screen.queryByTestId("leave-admin-row-r1")).toBeNull();
    });
  });

  it("search filters by employee name", async () => {
    setupMock({
      employees: [EMP_ADA, EMP_SIPHO],
      branches: [BRANCH_HQ, BRANCH_COASTAL],
      leaveTypes: [TYPE_ANNUAL],
      requestsPage1: [
        REQ("r1", "e1", "submitted"),
        REQ("r2", "e2", "submitted"),
      ],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-row-r1")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId("leave-admin-search"), {
      target: { value: "sipho" },
    });
    await waitFor(() => {
      expect(screen.getByTestId("leave-admin-row-r2")).toBeInTheDocument();
      expect(screen.queryByTestId("leave-admin-row-r1")).toBeNull();
    });
  });

  it("search filters by employee code", async () => {
    setupMock({
      employees: [EMP_ADA, EMP_SIPHO],
      branches: [BRANCH_HQ, BRANCH_COASTAL],
      leaveTypes: [TYPE_ANNUAL],
      requestsPage1: [
        REQ("r1", "e1", "submitted"),
        REQ("r2", "e2", "submitted"),
      ],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-row-r1")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId("leave-admin-search"), {
      target: { value: "EMP002" },
    });
    await waitFor(() => {
      expect(screen.getByTestId("leave-admin-row-r2")).toBeInTheDocument();
      expect(screen.queryByTestId("leave-admin-row-r1")).toBeNull();
    });
  });

  it("load more follows cursor and appends rows", async () => {
    const { calls } = setupMock({
      employees: [EMP_ADA],
      branches: [BRANCH_HQ],
      leaveTypes: [TYPE_ANNUAL],
      requestsPage1: [REQ("r1", "e1", "submitted")],
      requestsPage2: [REQ("r2", "e1", "approved")],
      nextCursor: "abc",
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-row-r1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-admin-load-more"));
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-row-r2")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("leave-admin-row-r1")).toBeInTheDocument();
    const withCursor = calls.filter((c) => c.url.includes("cursor=abc"));
    expect(withCursor.length).toBe(1);
  });

  it("load more retains client-side filters", async () => {
    setupMock({
      employees: [EMP_ADA, EMP_SIPHO],
      branches: [BRANCH_HQ, BRANCH_COASTAL],
      leaveTypes: [TYPE_ANNUAL],
      requestsPage1: [REQ("r1", "e1", "submitted")],
      requestsPage2: [
        REQ("r2", "e2", "submitted"),
        REQ("r3", "e1", "approved"),
      ],
      nextCursor: "abc",
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-row-r1")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId("leave-admin-search"), {
      target: { value: "ada" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-row-r1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-admin-load-more"));
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-row-r3")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("leave-admin-row-r2")).toBeNull();
  });

  it("open button navigates with returnTo state", async () => {
    setupMock({
      employees: [EMP_ADA],
      branches: [BRANCH_HQ],
      leaveTypes: [TYPE_ANNUAL],
      requestsPage1: [REQ("r1", "e1", "submitted")],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-row-r1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-admin-open-r1"));
    await waitFor(() =>
      expect(screen.getByTestId("detail-target")).toBeInTheDocument(),
    );
    const detail = screen.getByTestId("detail-target");
    expect(detail.textContent).toContain("returnTo");
    expect(detail.textContent).toContain("/leave/admin");
  });

  it("client-side filter warning is displayed", async () => {
    setupMock({
      employees: [EMP_ADA],
      branches: [BRANCH_HQ],
      leaveTypes: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-filter-note")).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("leave-admin-filter-note").textContent,
    ).toMatch(/loaded pages/i);
  });

  it("native status and client-side type filters combine", async () => {
    const { calls } = setupMock({
      employees: [EMP_ADA],
      branches: [BRANCH_HQ],
      leaveTypes: [TYPE_ANNUAL, TYPE_SICK],
      requestsPage1: [
        REQ("r1", "e1", "approved", "lt1"),
        REQ("r2", "e1", "approved", "lt2"),
      ],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-admin-row-r1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByText("Approved"));
    await waitFor(() => {
      const reqs = calls.filter((c) => c.url.includes("/leave/requests"));
      expect(reqs.some((c) => c.url.includes("status=approved"))).toBe(true);
    });
    fireEvent.click(screen.getByTestId("leave-admin-leave-type-filter"));
    const annual = await screen.findByRole("option", { name: "Annual Leave" });
    fireEvent.click(annual);
    await waitFor(() => {
      expect(screen.getByTestId("leave-admin-row-r1")).toBeInTheDocument();
      expect(screen.queryByTestId("leave-admin-row-r2")).toBeNull();
    });
  });
});