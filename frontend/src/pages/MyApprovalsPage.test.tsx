import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor, within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import {
  MemoryRouter, Route, Routes, useLocation,
} from "react-router-dom";

type MockMe = {
  id: string;
  username: string;
  role: string;
  employee_id: string | null;
  permissions: string[];
  must_change_password: boolean;
  default_timezone: string | null;
};

const { mockMeRef } = vi.hoisted(() => ({
  mockMeRef: {
    value: {
      id: "u-approver",
      username: "approver",
      role: "manager",
      employee_id: "e-mgr",
      permissions: ["self_view", "self_submit", "leave_approve"],
      must_change_password: false,
      default_timezone: null,
    } as MockMe,
  },
}));

vi.mock("../auth/useMe", () => ({
  useMe: () => ({
    data: mockMeRef.value,
    isLoading: false,
    isError: false,
    isSuccess: true,
  }),
}));

import { MyApprovalsPage } from "./MyApprovalsPage";

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

function setupMock(opts: {
  page1?: unknown[];
  page2?: unknown[];
  nextCursor?: string | null;
  status?: number;
}): { calls: Call[] } {
  const calls: Call[] = [];
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = requestUrl(input);
    const method =
      typeof Request !== "undefined" && input instanceof Request
        ? input.method
        : "GET";
    calls.push({ url, method });
    if (url.includes("/leave/requests")) {
      if (url.includes("cursor=")) {
        return jr({ items: opts.page2 ?? [], next_cursor: null });
      }
      return jr(
        { items: opts.page1 ?? [], next_cursor: opts.nextCursor ?? null },
        opts.status ?? 200,
      );
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function DetailStub() {
  const loc = useLocation();
  return <div data-testid="detail-target">{JSON.stringify(loc.state)}</div>;
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/leave/approvals"]}>
          <Routes>
            <Route path="/leave/approvals" element={<MyApprovalsPage />} />
            <Route path="/leave/requests/:id" element={<DetailStub />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

const REQ = (
  id: string,
  employee_id: string,
  employee_name: string | null,
  employee_code: string | null,
  leave_type_name: string | null,
  status = "submitted",
  approver_user_id: string | null = "u-approver",
  approver_role = "manager",
) => ({
  id,
  employee_id,
  leave_type_id: "lt1",
  from_date: "2026-06-01",
  to_date: "2026-06-03",
  days_requested: "3.00",
  reason: "Family",
  status,
  submitted_at: "2026-05-20T10:00:00Z",
  decided_at: null,
  decided_by_user_id: null,
  decision_note: null,
  row_version: 1,
  created_at: "2026-05-20T10:00:00Z",
  updated_at: "2026-05-20T10:00:00Z",
  captured_by_user_id: null,
  days: [],
  steps: [
    {
      id: "s1",
      leave_request_id: id,
      step_no: 1,
      approver_user_id,
      approver_role,
      status: "pending",
      decided_at: null,
      note: null,
      created_at: "2026-05-20T10:00:00Z",
    },
  ],
  employee_code,
  employee_name,
  leave_type_name,
});

beforeEach(() => {
  mockMeRef.value = {
    id: "u-approver",
    username: "approver",
    role: "manager",
    employee_id: "e-mgr",
    permissions: ["self_view", "self_submit", "leave_approve"],
    must_change_password: false,
    default_timezone: null,
  };
  vi.restoreAllMocks();
});
afterEach(() => { cleanup(); });

describe("MyApprovalsPage", () => {
  it("renders page header and My Leave link", async () => {
    setupMock({});
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("my-approvals-page")).toBeInTheDocument(),
    );
    expect(
      screen.getByText("My Approvals", { selector: "h2" }),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("my-approvals-my-leave-link"),
    ).toHaveAttribute("href", "/leave");
  });

  it("shows permission alert when user lacks leave_approve", async () => {
    mockMeRef.value = { ...mockMeRef.value, permissions: ["self_view"] };
    setupMock({});
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("approvals-no-permission"),
      ).toBeInTheDocument(),
    );
  });

  it("sends awaiting_approver_user_id equal to the current user's id", async () => {
    const { calls } = setupMock({});
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("my-approvals-page")).toBeInTheDocument(),
    );
    const reqCalls = calls.filter((c) => c.url.includes("/leave/requests"));
    expect(reqCalls.length).toBeGreaterThan(0);
    expect(reqCalls[0].url).toContain(
      "awaiting_approver_user_id=u-approver",
    );
    expect(reqCalls[0].url).toContain("status=submitted");
  });

  it("renders table with employee name, code, and leave type", async () => {
    setupMock({
      page1: [REQ("r1", "e1", "Ada Mokoena", "EMP001", "Annual Leave")],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("approvals-table")).toBeInTheDocument(),
    );
    const row = screen.getByTestId("approvals-row-r1");
    expect(within(row).getByText(/Ada Mokoena/)).toBeInTheDocument();
    expect(within(row).getByText(/EMP001/)).toBeInTheDocument();
    expect(within(row).getByText("Annual Leave")).toBeInTheDocument();
    expect(within(row).getByText("3.00")).toBeInTheDocument();
  });

  it("renders current pending step role as a badge", async () => {
    setupMock({
      page1: [
        REQ(
          "r1", "e1", "Ada", "EMP001", "Annual",
          "submitted", "u-approver", "manager",
        ),
      ],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("approvals-row-r1")).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("approvals-row-r1").textContent,
    ).toContain("manager");
  });

  it("shows empty state when there are no requests", async () => {
    setupMock({ page1: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("approvals-empty")).toBeInTheDocument(),
    );
  });

  it("shows error state on fetch failure", async () => {
    setupMock({ status: 500 });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("approvals-error")).toBeInTheDocument(),
    );
  });

  it("Open navigates to detail with returnTo state", async () => {
    setupMock({
      page1: [REQ("r1", "e1", "Ada", "EMP001", "Annual")],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("approvals-row-r1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("approvals-open-r1"));
    await waitFor(() =>
      expect(screen.getByTestId("detail-target")).toBeInTheDocument(),
    );
    const detail = screen.getByTestId("detail-target");
    expect(detail.textContent).toContain("returnTo");
    expect(detail.textContent).toContain("/leave/approvals");
  });

  it("load more follows cursor", async () => {
    const { calls } = setupMock({
      page1: [REQ("r1", "e1", "Ada", "EMP001", "Annual")],
      page2: [REQ("r2", "e2", "Sipho", "EMP002", "Sick")],
      nextCursor: "abc",
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("approvals-row-r1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("approvals-load-more"));
    await waitFor(() =>
      expect(screen.getByTestId("approvals-row-r2")).toBeInTheDocument(),
    );
    const withCursor = calls.filter((c) => c.url.includes("cursor=abc"));
    expect(withCursor.length).toBe(1);
  });

  it("null employee name falls back to code; null type shows em-dash", async () => {
    setupMock({
      page1: [REQ("r1", "e1", null, "EMP001", null)],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("approvals-row-r1")).toBeInTheDocument(),
    );
    const row = screen.getByTestId("approvals-row-r1");
    expect(within(row).getByText(/EMP001/)).toBeInTheDocument();
    expect(within(row).getByText("—")).toBeInTheDocument();
  });

  it("does not query when the user has no permissions", async () => {
    mockMeRef.value = { ...mockMeRef.value, permissions: [] };
    const { calls } = setupMock({});
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("approvals-no-permission"),
      ).toBeInTheDocument(),
    );
    const reqCalls = calls.filter((c) => c.url.includes("/leave/requests"));
    expect(reqCalls.length).toBe(0);
  });
});