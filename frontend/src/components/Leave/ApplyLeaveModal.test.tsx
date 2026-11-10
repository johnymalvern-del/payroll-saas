import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { ApplyLeaveModal } from "./ApplyLeaveModal";

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
  createResponse?: unknown;
  createStatus?: number;
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

    if (method === "POST" && url.endsWith("/leave/requests")) {
      return jr(
        opts.createResponse ?? {
          id: "r1",
          employee_id: "e1",
          leave_type_id: "lt1",
          from_date: "2026-03-10",
          to_date: "2026-03-14",
          days_requested: "5.00",
          reason: null,
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
        },
        opts.createStatus ?? 201,
      );
    }
    if (url.includes("/leave/types")) {
      return jr({ items: opts.types ?? [], next_cursor: null });
    }
    if (url.includes("/leave/balances")) {
      return jr({
        items: opts.balances ?? [],
        next_cursor: null,
        accrued_as_of: null,
        accrual_stale: false,
      });
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function renderModal(opts?: {
  onClose?: () => void;
  onCreated?: () => void;
}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <ApplyLeaveModal
          opened={true}
          onClose={opts?.onClose ?? (() => {})}
          employeeId="e1"
          onCreated={opts?.onCreated ?? (() => {})}
        />
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

const BAL = {
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

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("ApplyLeaveModal", () => {
  it("shows validation error if no leave type is selected", async () => {
    setupMock({ types: [TYPE_ANNUAL], balances: [BAL] });
    renderModal();
    await screen.findByTestId("apply-leave-type");
    fireEvent.click(screen.getByTestId("apply-leave-save-draft"));
    await waitFor(() =>
      expect(screen.getByTestId("apply-leave-error")).toHaveTextContent(
        /select a leave type/i,
      ),
    );
  });

  it("shows validation error if dates are missing", async () => {
    const { calls } = setupMock({ types: [TYPE_ANNUAL], balances: [BAL] });
    renderModal();
    await screen.findByTestId("apply-leave-type");
    fireEvent.click(screen.getByTestId("apply-leave-save-draft"));
    await waitFor(() =>
      expect(screen.getByTestId("apply-leave-error")).toBeInTheDocument(),
    );
    expect(calls.filter((c) => c.method === "POST").length).toBe(0);
  });

  it("shows validation error if end date precedes start date", async () => {
    setupMock({ types: [TYPE_ANNUAL], balances: [BAL] });
    renderModal();
    await screen.findByTestId("apply-leave-type");

    // Select leave type first so that the modal's validation order
    // reaches the date check.
    const typeSelect = screen.getByTestId("apply-leave-type");
    fireEvent.click(typeSelect);
    const option = await screen.findByText("Annual Leave (ANNUAL)");
    fireEvent.click(option);

    fireEvent.change(screen.getByTestId("apply-leave-from"), {
      target: { value: "2026-03-14" },
    });
    fireEvent.change(screen.getByTestId("apply-leave-to"), {
      target: { value: "2026-03-10" },
    });
    fireEvent.click(screen.getByTestId("apply-leave-save-draft"));
    await waitFor(() =>
      expect(screen.getByTestId("apply-leave-error")).toHaveTextContent(
        /end date must be on or after/i,
      ),
    );
  });

  it("posts a draft with the expected payload", async () => {
    const { calls } = setupMock({
      types: [TYPE_ANNUAL],
      balances: [BAL],
    });
    const onCreated = vi.fn();
    const onClose = vi.fn();
    renderModal({ onCreated, onClose });
    await screen.findByTestId("apply-leave-type");

    const typeSelect = screen.getByTestId("apply-leave-type");
    fireEvent.click(typeSelect);
    const option = await screen.findByText("Annual Leave (ANNUAL)");
    fireEvent.click(option);

    fireEvent.change(screen.getByTestId("apply-leave-from"), {
      target: { value: "2026-03-10" },
    });
    fireEvent.change(screen.getByTestId("apply-leave-to"), {
      target: { value: "2026-03-14" },
    });
    fireEvent.change(screen.getByTestId("apply-leave-reason"), {
      target: { value: "Family event" },
    });

    fireEvent.click(screen.getByTestId("apply-leave-save-draft"));

    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.endsWith("/leave/requests"),
      );
      expect(post).toBeDefined();
      const parsed = JSON.parse(post!.body);
      expect(parsed.employee_id).toBe("e1");
      expect(parsed.leave_type_id).toBe("lt1");
      expect(parsed.from_date).toBe("2026-03-10");
      expect(parsed.to_date).toBe("2026-03-14");
      expect(parsed.reason).toBe("Family event");
    });

    await waitFor(() => {
      expect(onCreated).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("surfaces backend error on create failure", async () => {
    setupMock({
      types: [TYPE_ANNUAL],
      balances: [BAL],
      createStatus: 422,
      createResponse: { error: { code: "no_working_days" } },
    });
    renderModal();
    await screen.findByTestId("apply-leave-type");

    const typeSelect = screen.getByTestId("apply-leave-type");
    fireEvent.click(typeSelect);
    const option = await screen.findByText("Annual Leave (ANNUAL)");
    fireEvent.click(option);

    fireEvent.change(screen.getByTestId("apply-leave-from"), {
      target: { value: "2026-03-14" },
    });
    fireEvent.change(screen.getByTestId("apply-leave-to"), {
      target: { value: "2026-03-15" },
    });
    fireEvent.click(screen.getByTestId("apply-leave-save-draft"));

    await waitFor(() =>
      expect(screen.getByTestId("apply-leave-error")).toHaveTextContent(
        /no working days/i,
      ),
    );
  });

  it("shows selected type's available balance hint", async () => {
    setupMock({ types: [TYPE_ANNUAL], balances: [BAL] });
    renderModal();
    await screen.findByTestId("apply-leave-type");

    const typeSelect = screen.getByTestId("apply-leave-type");
    fireEvent.click(typeSelect);
    const option = await screen.findByText("Annual Leave (ANNUAL)");
    fireEvent.click(option);

    await waitFor(() =>
      expect(
        screen.getByTestId("apply-leave-balance-hint"),
      ).toHaveTextContent(/Available: 12\.00 days/),
    );
  });
});