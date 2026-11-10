import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { AdjustBalanceModal } from "./AdjustBalanceModal";
import type { LeaveBalanceOut } from "../../api/leaveBalances";

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

const BAL_OPEN: LeaveBalanceOut = {
  id: "b1",
  employee_id: "e1",
  leave_type_id: "lt1",
  cycle_start: "2026-01-01",
  cycle_end: "2099-12-31",
  entitled: "20.0000",
  accrued: "10.0000",
  taken: "2.0000",
  pending: "0.0000",
  carried_in: "0.0000",
  adjusted: "0.0000",
  available: "8.0000",
  row_version: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const BAL_CLOSED: LeaveBalanceOut = {
  ...BAL_OPEN,
  cycle_start: "2024-01-01",
  cycle_end: "2024-12-31",
};

function setupMock(opts: {
  status?: number;
  body?: unknown;
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
    if (method === "POST" && url.includes("/leave/balances/adjust")) {
      return jr(opts.body ?? { balance: BAL_OPEN, ledger_entry_id: "lg1" }, opts.status ?? 200);
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function renderModal(opts: {
  balance?: LeaveBalanceOut;
  onClose?: () => void;
  onSuccess?: () => void;
} = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onClose = opts.onClose ?? vi.fn();
  const onSuccess = opts.onSuccess ?? vi.fn();
  const result = render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <AdjustBalanceModal
          opened={true}
          onClose={onClose}
          balance={opts.balance ?? BAL_OPEN}
          employeeLabel="Ada Mokoena (EMP001)"
          leaveTypeLabel="Annual Leave"
          onSuccess={onSuccess}
        />
      </QueryClientProvider>
    </MantineProvider>,
  );
  return { onClose, onSuccess, ...result };
}

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("AdjustBalanceModal", () => {
  it("renders employee, type, cycle, and current available", () => {
    setupMock();
    renderModal();
    const root = screen.getByTestId("adjust-balance-modal");
    expect(root.textContent).toContain("Ada Mokoena");
    expect(root.textContent).toContain("Annual Leave");
    expect(screen.getByTestId("adjust-modal-cycle").textContent).toContain("2026-01-01");
    expect(root.textContent).toContain("8.00");
  });

  it("confirm is disabled until delta and reason provided", () => {
    setupMock();
    renderModal();
    expect(screen.getByTestId("adjust-modal-confirm")).toBeDisabled();
    fireEvent.change(screen.getByTestId("adjust-modal-delta"), {
      target: { value: "5" },
    });
    expect(screen.getByTestId("adjust-modal-confirm")).toBeDisabled();
    fireEvent.change(screen.getByTestId("adjust-modal-reason"), {
      target: { value: "Bonus" },
    });
    expect(screen.getByTestId("adjust-modal-confirm")).not.toBeDisabled();
  });

  it("confirm posts delta and reason", async () => {
    const { calls } = setupMock();
    const { onSuccess } = renderModal();
    fireEvent.change(screen.getByTestId("adjust-modal-delta"), {
      target: { value: "5" },
    });
    fireEvent.change(screen.getByTestId("adjust-modal-reason"), {
      target: { value: "Bonus" },
    });
    fireEvent.click(screen.getByTestId("adjust-modal-confirm"));
    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.includes("/leave/balances/adjust"),
      );
      expect(post).toBeDefined();
      const parsed = JSON.parse(post!.body);
      expect(parsed.delta).toBe("5");
      expect(parsed.reason).toBe("Bonus");
      expect(parsed.employee_id).toBe("e1");
      expect(parsed.leave_type_id).toBe("lt1");
    });
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it("accepts negative delta", async () => {
    const { calls } = setupMock();
    renderModal();
    fireEvent.change(screen.getByTestId("adjust-modal-delta"), {
      target: { value: "-2.5" },
    });
    fireEvent.change(screen.getByTestId("adjust-modal-reason"), {
      target: { value: "Correction" },
    });
    fireEvent.click(screen.getByTestId("adjust-modal-confirm"));
    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST");
      expect(JSON.parse(post!.body).delta).toBe("-2.5");
    });
  });

  it("surfaces insufficient_balance", async () => {
    setupMock({
      status: 422,
      body: { error: { code: "insufficient_balance" } },
    });
    renderModal();
    fireEvent.change(screen.getByTestId("adjust-modal-delta"), {
      target: { value: "-50" },
    });
    fireEvent.change(screen.getByTestId("adjust-modal-reason"), {
      target: { value: "Too big" },
    });
    fireEvent.click(screen.getByTestId("adjust-modal-confirm"));
    await waitFor(() =>
      expect(screen.getByTestId("adjust-modal-error")).toHaveTextContent(
        /negative, which is not allowed/i,
      ),
    );
  });

  it("surfaces forbidden", async () => {
    setupMock({
      status: 403,
      body: { error: { code: "forbidden" } },
    });
    renderModal();
    fireEvent.change(screen.getByTestId("adjust-modal-delta"), {
      target: { value: "1" },
    });
    fireEvent.change(screen.getByTestId("adjust-modal-reason"), {
      target: { value: "Late" },
    });
    fireEvent.click(screen.getByTestId("adjust-modal-confirm"));
    await waitFor(() =>
      expect(screen.getByTestId("adjust-modal-error")).toHaveTextContent(
        /permission to adjust/i,
      ),
    );
  });

  it("shows closed-cycle warning", () => {
    setupMock();
    renderModal({ balance: BAL_CLOSED });
    expect(
      screen.getByTestId("adjust-modal-closed-warning"),
    ).toBeInTheDocument();
  });

  it("does not show closed-cycle warning for open cycle", () => {
    setupMock();
    renderModal({ balance: BAL_OPEN });
    expect(screen.queryByTestId("adjust-modal-closed-warning")).toBeNull();
  });

  it("cancel closes without POST", async () => {
    const { calls } = setupMock();
    const { onClose } = renderModal();
    fireEvent.click(screen.getByTestId("adjust-modal-cancel"));
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.filter((c) => c.method === "POST").length).toBe(0);
    expect(onClose).toHaveBeenCalled();
  });
});