import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor,
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

import { LeaveRequestDetailPage } from "./LeaveRequestDetailPage";

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
  request?: unknown;
  requestStatus?: number;
  types?: unknown[];
  submitStatus?: number;
  submitResponse?: unknown;
  cancelStatus?: number;
  cancelResponse?: unknown;
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

    if (method === "POST" && url.endsWith("/submit")) {
      return jr(
        opts.submitResponse ?? { ...(opts.request as object), status: "submitted" },
        opts.submitStatus ?? 200,
      );
    }
    if (method === "POST" && url.endsWith("/cancel")) {
      return jr(
        opts.cancelResponse ?? { ...(opts.request as object), status: "cancelled" },
        opts.cancelStatus ?? 200,
      );
    }
    if (url.includes("/leave/types")) {
      return jr({ items: opts.types ?? [], next_cursor: null });
    }
    if (/\/leave\/requests\/[^/?]+$/.test(url)) {
      return jr(
        opts.request ?? {},
        opts.requestStatus ?? 200,
      );
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function renderPage(path = "/leave/requests/r1") {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route
              path="/leave/requests/:id"
              element={<LeaveRequestDetailPage />}
            />
            <Route
              path="/leave/history"
              element={<div data-testid="history-target">History</div>}
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

const STEP_PENDING = {
  id: "s1",
  leave_request_id: "r1",
  step_no: 1,
  approver_user_id: null,
  approver_role: "manager",
  status: "pending",
  decided_at: null,
  note: null,
  created_at: "2026-02-01T10:00:00Z",
};

const BASE_REQUEST = {
  id: "r1",
  employee_id: "e1",
  leave_type_id: "lt1",
  from_date: "2026-03-10",
  to_date: "2026-03-14",
  days_requested: "5.00",
  reason: "Family event",
  status: "draft",
  submitted_at: null,
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

describe("LeaveRequestDetailPage", () => {
  it("renders header with type name, dates, days, status badge", async () => {
    setupMock({
      request: { ...BASE_REQUEST, status: "draft" },
      types: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-title")).toHaveTextContent(
        "Annual Leave",
      ),
    );
    expect(screen.getByTestId("leave-request-dates")).toHaveTextContent(
      "2026-03-10 → 2026-03-14",
    );
    expect(screen.getByTestId("leave-request-dates")).toHaveTextContent("5.00");
    expect(screen.getByTestId("leave-request-status")).toHaveTextContent("draft");
  });

  it("renders reason and metadata", async () => {
    setupMock({
      request: { ...BASE_REQUEST, reason: "Family event" },
      types: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-detail-page")).toBeInTheDocument(),
    );
    expect(screen.getByText("Family event")).toBeInTheDocument();
  });

  it("renders approval timeline with steps", async () => {
    setupMock({
      request: {
        ...BASE_REQUEST,
        status: "submitted",
        submitted_at: "2026-02-01T10:00:00Z",
        steps: [STEP_PENDING],
      },
      types: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-timeline")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("leave-request-step-1")).toBeInTheDocument();
    expect(screen.getByTestId("leave-request-step-1")).toHaveTextContent(
      "manager",
    );
  });

  it("shows empty timeline message for draft", async () => {
    setupMock({
      request: { ...BASE_REQUEST, status: "draft", steps: [] },
      types: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-no-steps")).toBeInTheDocument(),
    );
  });

  it("shows error state on load failure", async () => {
    setupMock({
      request: { error: { code: "boom" } },
      requestStatus: 500,
      types: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-error")).toBeInTheDocument(),
    );
  });

  it("draft status shows Edit, Submit, Cancel buttons", async () => {
    setupMock({
      request: { ...BASE_REQUEST, status: "draft" },
      types: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-edit")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("leave-request-submit")).toBeInTheDocument();
    expect(screen.getByTestId("leave-request-cancel")).toBeInTheDocument();
  });

  it("submitted status shows only Cancel", async () => {
    setupMock({
      request: { ...BASE_REQUEST, status: "submitted", steps: [STEP_PENDING] },
      types: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-cancel")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("leave-request-edit")).toBeNull();
    expect(screen.queryByTestId("leave-request-submit")).toBeNull();
  });

  it("approved status shows only Cancel", async () => {
    setupMock({
      request: { ...BASE_REQUEST, status: "approved" },
      types: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-cancel")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("leave-request-edit")).toBeNull();
    expect(screen.queryByTestId("leave-request-submit")).toBeNull();
  });

  it("rejected status shows no action buttons", async () => {
    setupMock({
      request: { ...BASE_REQUEST, status: "rejected" },
      types: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-no-actions")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("leave-request-edit")).toBeNull();
    expect(screen.queryByTestId("leave-request-submit")).toBeNull();
    expect(screen.queryByTestId("leave-request-cancel")).toBeNull();
  });

  it("cancelled status shows no action buttons", async () => {
    setupMock({
      request: { ...BASE_REQUEST, status: "cancelled" },
      types: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-no-actions")).toBeInTheDocument(),
    );
  });

  it("Edit button opens modal with prefilled values", async () => {
    setupMock({
      request: { ...BASE_REQUEST, status: "draft" },
      types: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-edit")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-request-edit"));
    await waitFor(() => {
      const from = screen.getByTestId("apply-leave-from") as HTMLInputElement;
      expect(from.value).toBe("2026-03-10");
    });
  });

  it("Submit button confirms and POSTs to /submit", async () => {
    const { calls } = setupMock({
      request: { ...BASE_REQUEST, status: "draft" },
      types: [TYPE_ANNUAL],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-submit")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-request-submit"));
    await waitFor(() => {
      expect(
        calls.some(
          (c) => c.method === "POST" && c.url.endsWith("/r1/submit"),
        ),
      ).toBe(true);
    });
  });

  it("Submit does nothing when confirm is cancelled", async () => {
    const { calls } = setupMock({
      request: { ...BASE_REQUEST, status: "draft" },
      types: [TYPE_ANNUAL],
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-submit")).toBeInTheDocument(),
    );
    const before = calls.filter((c) => c.method === "POST").length;
    fireEvent.click(screen.getByTestId("leave-request-submit"));
    await new Promise((r) => setTimeout(r, 50));
    const after = calls.filter((c) => c.method === "POST").length;
    expect(after).toBe(before);
  });

  it("Cancel on draft confirms and POSTs to /cancel", async () => {
    const { calls } = setupMock({
      request: { ...BASE_REQUEST, status: "draft" },
      types: [TYPE_ANNUAL],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-cancel")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-request-cancel"));
    await waitFor(() => {
      expect(
        calls.some(
          (c) => c.method === "POST" && c.url.endsWith("/r1/cancel"),
        ),
      ).toBe(true);
    });
  });

  it("Cancel on approved shows a distinct confirm message", async () => {
    setupMock({
      request: { ...BASE_REQUEST, status: "approved" },
      types: [TYPE_ANNUAL],
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-cancel")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-request-cancel"));
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled();
      const msg = confirmSpy.mock.calls[0][0] as string;
      expect(msg).toMatch(/taken leave will be reversed/i);
    });
  });

  it("surfaces no_eligible_approver on submit failure", async () => {
    setupMock({
      request: { ...BASE_REQUEST, status: "draft" },
      types: [TYPE_ANNUAL],
      submitStatus: 409,
      submitResponse: { error: { code: "no_eligible_approver" } },
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-submit")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-request-submit"));
    await waitFor(() =>
      expect(
        screen.getByTestId("leave-request-action-error"),
      ).toHaveTextContent(/No approver is available/i),
    );
  });

  it("surfaces cannot_cancel_after_days_taken with dates", async () => {
    setupMock({
      request: { ...BASE_REQUEST, status: "approved" },
      types: [TYPE_ANNUAL],
      cancelStatus: 409,
      cancelResponse: {
        error: {
          code: "cannot_cancel_after_days_taken",
          details: { started_days: ["2026-03-10", "2026-03-11"] },
        },
      },
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-cancel")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-request-cancel"));
    await waitFor(() =>
      expect(
        screen.getByTestId("leave-request-action-error"),
      ).toHaveTextContent(/2026-03-10, 2026-03-11/),
    );
  });

  it("back link points to /leave/history", async () => {
    setupMock({
      request: { ...BASE_REQUEST, status: "draft" },
      types: [TYPE_ANNUAL],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-request-back-link")).toHaveAttribute(
        "href",
        "/leave/history",
      ),
    );
  });
});