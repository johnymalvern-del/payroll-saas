import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { DecisionModal } from "./DecisionModal";
import type {
  LeaveApprovalStepOut,
  LeaveRequestOut,
} from "../../api/leaveRequests";

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

const STEP: LeaveApprovalStepOut = {
  id: "s1",
  leave_request_id: "r1",
  step_no: 1,
  approver_user_id: "u1",
  approver_role: "manager",
  status: "pending",
  decided_at: null,
  note: null,
  created_at: "2026-02-01T10:00:00Z",
};

const REQ: LeaveRequestOut = {
  id: "r1",
  employee_id: "e1",
  leave_type_id: "lt1",
  from_date: "2026-03-10",
  to_date: "2026-03-14",
  days_requested: "5.00",
  reason: "Family event",
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
  steps: [STEP],
  employee_code: "EMP001",
  employee_name: "Ada Mokoena",
  leave_type_name: "Annual Leave",
};

function setupMock(opts: {
  decideResponse?: unknown;
  decideStatus?: number;
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
    if (method === "POST" && /\/steps\/[^/]+\/decide$/.test(url)) {
      return jr(
        opts.decideResponse ?? { ...REQ, status: "approved" },
        opts.decideStatus ?? 200,
      );
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function renderModal(
  opts: {
    mode?: "approve" | "reject";
    onClose?: () => void;
    onSuccess?: () => void;
  } = {},
) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const onClose = opts.onClose ?? vi.fn();
  const onSuccess = opts.onSuccess ?? vi.fn();
  const result = render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <DecisionModal
          opened={true}
          onClose={onClose}
          mode={opts.mode ?? "approve"}
          request={REQ}
          step={STEP}
          onSuccess={onSuccess}
        />
      </QueryClientProvider>
    </MantineProvider>,
  );
  return { onClose, onSuccess, ...result };
}

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("DecisionModal", () => {
  it("renders employee, type, dates, reason, and step", () => {
    setupMock();
    renderModal({ mode: "approve" });
    const root = screen.getByTestId("decision-modal");
    expect(root.textContent).toContain("Ada Mokoena");
    expect(root.textContent).toContain("EMP001");
    expect(root.textContent).toContain("Annual Leave");
    expect(root.textContent).toContain("Family event");
    expect(root.textContent).toContain("manager");
  });

  it("approve mode: confirm sends approve=true with no note", async () => {
    const { calls } = setupMock();
    const { onSuccess } = renderModal({ mode: "approve" });
    fireEvent.click(screen.getByTestId("decision-modal-confirm"));
    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && /\/steps\/s1\/decide$/.test(c.url),
      );
      expect(post).toBeDefined();
      const parsed = JSON.parse(post!.body);
      expect(parsed.approve).toBe(true);
      expect(parsed.note).toBeNull();
    });
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it("approve mode: confirm sends note when provided", async () => {
    const { calls } = setupMock();
    renderModal({ mode: "approve" });
    fireEvent.change(screen.getByTestId("decision-modal-note"), {
      target: { value: "Looks good" },
    });
    fireEvent.click(screen.getByTestId("decision-modal-confirm"));
    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST");
      expect(post).toBeDefined();
      const parsed = JSON.parse(post!.body);
      expect(parsed.approve).toBe(true);
      expect(parsed.note).toBe("Looks good");
    });
  });

  it("reject mode: confirm disabled without note", () => {
    setupMock();
    renderModal({ mode: "reject" });
    expect(screen.getByTestId("decision-modal-confirm")).toBeDisabled();
  });

  it("reject mode: confirm sends approve=false with note", async () => {
    const { calls } = setupMock();
    renderModal({ mode: "reject" });
    fireEvent.change(screen.getByTestId("decision-modal-note"), {
      target: { value: "Insufficient notice" },
    });
    fireEvent.click(screen.getByTestId("decision-modal-confirm"));
    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST");
      const parsed = JSON.parse(post!.body);
      expect(parsed.approve).toBe(false);
      expect(parsed.note).toBe("Insufficient notice");
    });
  });

  it("surfaces self_approval_forbidden", async () => {
    setupMock({
      decideStatus: 403,
      decideResponse: { error: { code: "self_approval_forbidden" } },
    });
    renderModal({ mode: "approve" });
    fireEvent.click(screen.getByTestId("decision-modal-confirm"));
    await waitFor(() =>
      expect(screen.getByTestId("decision-modal-error")).toHaveTextContent(
        /cannot approve your own/i,
      ),
    );
  });

  it("surfaces wrong_approver", async () => {
    setupMock({
      decideStatus: 403,
      decideResponse: { error: { code: "wrong_approver" } },
    });
    renderModal({ mode: "approve" });
    fireEvent.click(screen.getByTestId("decision-modal-confirm"));
    await waitFor(() =>
      expect(screen.getByTestId("decision-modal-error")).toHaveTextContent(
        /not the assigned approver/i,
      ),
    );
  });

  it("cancel closes without POST", async () => {
    const { calls } = setupMock();
    const { onClose } = renderModal({ mode: "approve" });
    fireEvent.click(screen.getByTestId("decision-modal-cancel"));
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.filter((c) => c.method === "POST").length).toBe(0);
    expect(onClose).toHaveBeenCalled();
  });
});