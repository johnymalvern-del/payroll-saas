import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { LeaveTypeFormModal } from "./LeaveTypeFormModal";
import type { LeaveTypeOut } from "../../api/leaveTypes";

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

const TYPE_ANNUAL: LeaveTypeOut = {
  id: "lt1",
  name: "Annual Leave",
  code: "annual",
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
  row_version: 3,
  approval_chain: ["manager", "hr"],
  requires_payroll_admin_final: false,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
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
    if (
      method === "POST" &&
      (url.endsWith("/leave/types") || url.match(/\/leave\/types\/[^/]+$/))
    ) {
      return jr(opts.body ?? TYPE_ANNUAL, opts.status ?? 200);
    }
    if (method === "PATCH" && url.match(/\/leave\/types\/[^/]+$/)) {
      return jr(opts.body ?? TYPE_ANNUAL, opts.status ?? 200);
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function renderModal(opts: {
  initialType?: LeaveTypeOut | null;
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
        <LeaveTypeFormModal
          opened={true}
          onClose={onClose}
          initialType={opts.initialType ?? null}
          onSuccess={onSuccess}
        />
      </QueryClientProvider>
    </MantineProvider>,
  );
  return { onClose, onSuccess, ...result };
}

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("LeaveTypeFormModal", () => {
  it("create mode: renders empty form", () => {
    setupMock();
    renderModal();
    const name = screen.getByTestId("leave-type-form-name") as HTMLInputElement;
    const code = screen.getByTestId("leave-type-form-code") as HTMLInputElement;
    expect(name.value).toBe("");
    expect(code.value).toBe("");
    expect(code).not.toBeDisabled();
  });

  it("create mode: blocks submit without name", async () => {
    const { calls } = setupMock();
    renderModal();
    fireEvent.click(screen.getByTestId("leave-type-form-confirm"));
    await waitFor(() =>
      expect(
        screen.getByTestId("leave-type-form-validation"),
      ).toHaveTextContent(/Name is required/i),
    );
    expect(calls.filter((c) => c.method === "POST").length).toBe(0);
  });

  it("create mode: blocks submit without code", async () => {
    const { calls } = setupMock();
    renderModal();
    fireEvent.change(screen.getByTestId("leave-type-form-name"), {
      target: { value: "Sick Leave" },
    });
    fireEvent.click(screen.getByTestId("leave-type-form-confirm"));
    await waitFor(() =>
      expect(
        screen.getByTestId("leave-type-form-validation"),
      ).toHaveTextContent(/Code is required/i),
    );
    expect(calls.filter((c) => c.method === "POST").length).toBe(0);
  });

  it("create mode: POSTs with lowercased code and required fields", async () => {
    const { calls } = setupMock();
    const { onSuccess } = renderModal();
    fireEvent.change(screen.getByTestId("leave-type-form-name"), {
      target: { value: "Sick Leave" },
    });
    fireEvent.change(screen.getByTestId("leave-type-form-code"), {
      target: { value: "SICK" },
    });
    fireEvent.click(screen.getByTestId("leave-type-form-confirm"));
    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST");
      expect(post).toBeDefined();
      const body = JSON.parse(post!.body);
      expect(body.name).toBe("Sick Leave");
      expect(body.code).toBe("sick");
    });
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it("create mode: maps duplicate_code", async () => {
    setupMock({
      status: 409,
      body: { error: { code: "duplicate_code" } },
    });
    renderModal();
    fireEvent.change(screen.getByTestId("leave-type-form-name"), {
      target: { value: "Annual" },
    });
    fireEvent.change(screen.getByTestId("leave-type-form-code"), {
      target: { value: "annual" },
    });
    fireEvent.click(screen.getByTestId("leave-type-form-confirm"));
    await waitFor(() =>
      expect(screen.getByTestId("leave-type-form-error")).toHaveTextContent(
        /already exists/i,
      ),
    );
  });

  it("edit mode: prefills from initialType and disables code", () => {
    setupMock();
    renderModal({ initialType: TYPE_ANNUAL });
    const name = screen.getByTestId("leave-type-form-name") as HTMLInputElement;
    const code = screen.getByTestId("leave-type-form-code") as HTMLInputElement;
    expect(name.value).toBe("Annual Leave");
    expect(code.value).toBe("annual");
    expect(code).toBeDisabled();
  });

  it("edit mode: PATCHes with row_version and no code", async () => {
    const { calls } = setupMock();
    const { onSuccess } = renderModal({ initialType: TYPE_ANNUAL });
    fireEvent.change(screen.getByTestId("leave-type-form-name"), {
      target: { value: "Annual Leave (v2)" },
    });
    fireEvent.click(screen.getByTestId("leave-type-form-confirm"));
    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH");
      expect(patch).toBeDefined();
      const body = JSON.parse(patch!.body);
      expect(body.row_version).toBe(3);
      expect(body.name).toBe("Annual Leave (v2)");
      expect(body.code).toBeUndefined();
    });
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it("edit mode: maps record_changed with current version", async () => {
    setupMock({
      status: 409,
      body: {
        error: {
          code: "record_changed",
          details: { current_row_version: 5 },
        },
      },
    });
    renderModal({ initialType: TYPE_ANNUAL });
    fireEvent.click(screen.getByTestId("leave-type-form-confirm"));
    await waitFor(() =>
      expect(screen.getByTestId("leave-type-form-error")).toHaveTextContent(
        /current version 5/i,
      ),
    );
  });

  it("clears max_carryover when cycle set to fixed", () => {
    setupMock();
    renderModal({ initialType: TYPE_ANNUAL });
    fireEvent.change(screen.getByTestId("leave-type-form-max-carryover"), {
      target: { value: "5" },
    });
    const maxCarry = screen.getByTestId(
      "leave-type-form-max-carryover",
    ) as HTMLInputElement;
    expect(maxCarry.value).toBe("5");
    // Change cycle to fixed
    fireEvent.click(screen.getByTestId("leave-type-form-cycle"));
    fireEvent.click(screen.getByRole("option", { name: "Fixed anchor" }));
    expect(maxCarry.value).toBe("");
    expect(maxCarry).toBeDisabled();
  });

  it("cancel closes without POST or PATCH", async () => {
    const { calls } = setupMock();
    const { onClose } = renderModal();
    fireEvent.click(screen.getByTestId("leave-type-form-cancel"));
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.filter((c) => c.method !== "GET").length).toBe(0);
    expect(onClose).toHaveBeenCalled();
  });
});