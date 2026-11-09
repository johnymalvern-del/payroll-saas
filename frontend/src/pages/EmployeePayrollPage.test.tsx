import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { EmployeePayrollPage } from "./EmployeePayrollPage";

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
  structures?: unknown[];
  assignments?: unknown[];
  collisions?: unknown;
  submitResponse?: unknown;
  submitStatus?: number;
  approveResponse?: unknown;
  approveStatus?: number;
  rejectResponse?: unknown;
  rejectStatus?: number;
  cancelResponse?: unknown;
  cancelStatus?: number;
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

    if (method === "POST" && url.endsWith("/approve")) {
      return jr(
        opts.approveResponse ?? {
          ...(opts.assignments && (opts.assignments[0] as object) || {}),
          status: "approved",
          children: [],
        },
        opts.approveStatus ?? 200,
      );
    }
    if (method === "POST" && url.endsWith("/reject")) {
      return jr(
        opts.rejectResponse ?? {
          ...(opts.assignments && (opts.assignments[0] as object) || {}),
          status: "rejected",
        },
        opts.rejectStatus ?? 200,
      );
    }
    if (method === "POST" && url.endsWith("/cancel")) {
      return jr(
        opts.cancelResponse ?? {
          ...(opts.assignments && (opts.assignments[0] as object) || {}),
          status: "cancelled",
        },
        opts.cancelStatus ?? 200,
      );
    }
    if (url.includes("/check-collisions")) {
      return jr(
        opts.collisions ?? {
          employee_id: "e1",
          structure_id: "s1",
          effective_from: "2026-12-01",
          manual: [],
          structure_owned: [],
        },
      );
    }
    if (
      method === "POST" &&
      url.endsWith("/payroll/employee-salary-assignments")
    ) {
      return jr(
        opts.submitResponse ?? {
          id: "a1", employee_id: "e1", structure_id: "s1",
          effective_from: "2026-12-01", effective_to: null,
          status: "pending", idempotency_key: null,
          submitted_by_user_id: "u1", submitted_at: "2026-11-09T10:00:00Z",
          decided_by_user_id: null, decided_at: null,
          decision_note: null, failure_detail: null,
          override_manual_ids: [], row_version: 1,
          created_at: "2026-11-09T10:00:00Z",
          updated_at: "2026-11-09T10:00:00Z",
        },
        opts.submitStatus ?? 201,
      );
    }
    if (url.includes("/employees/e1/salary-assignments")) {
      return jr({ items: opts.assignments ?? [] });
    }
    if (url.includes("/payroll/salary-structures")) {
      return jr({ items: opts.structures ?? [] });
    }
    if (url.includes("/api/v1/employees")) {
      return jr({ items: opts.employees ?? [], next_cursor: null });
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function renderPage(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route
              path="/payroll/employee-payroll"
              element={<EmployeePayrollPage />}
            />
            <Route
              path="/payroll/employee-payroll/:employeeId"
              element={<EmployeePayrollPage />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

const EMP = {
  id: "e1", employee_code: "EMP001",
  first_name: "Ada", last_name: "Lovelace",
};
const ST = {
  id: "s1", structure_group_id: "g1", version_number: 1,
  is_current: true, name: "Monthly Basic", description: null,
  pay_basis: "monthly", base_rate: "18000", is_active: true,
  row_version: 1,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  components: [],
};
const ASSIGN_PENDING = {
  id: "a1", employee_id: "e1", structure_id: "s1",
  effective_from: "2026-12-01", effective_to: null,
  status: "pending", idempotency_key: null,
  submitted_by_user_id: "u1", submitted_at: "2026-11-09T10:00:00Z",
  decided_by_user_id: null, decided_at: null,
  decision_note: null, failure_detail: null,
  override_manual_ids: [], row_version: 1,
  created_at: "2026-11-09T10:00:00Z",
  updated_at: "2026-11-09T10:00:00Z",
};
const ASSIGN_APPROVED = { ...ASSIGN_PENDING, id: "a2", status: "approved" };

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("EmployeePayrollPage — index", () => {
  it("renders the index when no employeeId is in the URL", async () => {
    setupMock({ employees: [EMP] });
    renderPage("/payroll/employee-payroll");
    await waitFor(() =>
      expect(screen.getByTestId("employee-payroll-index")).toBeInTheDocument(),
    );
  });

  it("lists employees with a link to each payroll", async () => {
    setupMock({ employees: [EMP] });
    renderPage("/payroll/employee-payroll");
    await waitFor(() =>
      expect(screen.getByTestId("employees-table")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("employee-row-e1")).toBeInTheDocument();
    expect(screen.getByTestId("employee-open-e1")).toHaveAttribute(
      "href", "/payroll/employee-payroll/e1",
    );
  });
});

describe("EmployeePayrollPage — detail", () => {
  it("renders employee name and empty assignments", async () => {
    setupMock({ employees: [EMP], assignments: [] });
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("employee-name")).toHaveTextContent(
        "Ada Lovelace",
      ),
    );
    expect(screen.getByTestId("assignments-empty")).toBeInTheDocument();
  });

  it("renders assignments table when present", async () => {
    setupMock({ employees: [EMP], assignments: [ASSIGN_PENDING] });
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("assignments-table")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("assignment-row-a1")).toBeInTheDocument();
  });

  it("opens the submit form when New assignment clicked", async () => {
    setupMock({ employees: [EMP], structures: [ST], assignments: [] });
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("new-assignment-button")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("new-assignment-button"));
    expect(screen.getByTestId("assignment-form")).toBeInTheDocument();
  });

  it("check-collisions is called with the chosen structure/date", async () => {
    const { calls } = setupMock({
      employees: [EMP], structures: [ST], assignments: [],
    });
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("new-assignment-button")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("new-assignment-button"));
    fireEvent.change(screen.getByTestId("form-structure"), {
      target: { value: "s1" },
    });
    fireEvent.change(screen.getByTestId("form-effective-from"), {
      target: { value: "2026-12-01" },
    });
    const check = screen.getByTestId("check-collisions-button");
    fireEvent.click(check);
    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.includes("/check-collisions"),
      );
      expect(post).toBeDefined();
      const body = JSON.parse(post!.body);
      expect(body.structure_id).toBe("s1");
      expect(body.effective_from).toBe("2026-12-01");
      expect(body.employee_id).toBe("e1");
    });
  });

  it("shows no-collisions alert when there are none", async () => {
    setupMock({ employees: [EMP], structures: [ST], assignments: [] });
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("new-assignment-button")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("new-assignment-button"));
    fireEvent.change(screen.getByTestId("form-structure"), {
      target: { value: "s1" },
    });
    fireEvent.change(screen.getByTestId("form-effective-from"), {
      target: { value: "2026-12-01" },
    });
    fireEvent.click(screen.getByTestId("check-collisions-button"));
    await waitFor(() =>
      expect(screen.getByTestId("no-collisions")).toBeInTheDocument(),
    );
  });

  it("shows manual overlaps with checkboxes", async () => {
    setupMock({
      employees: [EMP], structures: [ST], assignments: [],
      collisions: {
        employee_id: "e1",
        structure_id: "s1",
        effective_from: "2026-12-01",
        manual: [
          {
            kind: "employee_earning",
            id: "me1",
            component_kind: "earning",
            component_type_id: "et1",
            effective_from: "2026-01-01",
            effective_to: null,
            status: "requires_override",
          },
        ],
        structure_owned: [],
      },
    });
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("new-assignment-button")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("new-assignment-button"));
    fireEvent.change(screen.getByTestId("form-structure"), {
      target: { value: "s1" },
    });
    fireEvent.change(screen.getByTestId("form-effective-from"), {
      target: { value: "2026-12-01" },
    });
    fireEvent.click(screen.getByTestId("check-collisions-button"));
    await waitFor(() =>
      expect(screen.getByTestId("manual-overlap-me1")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("override-checkbox-me1")).toBeInTheDocument();
  });

  it("submit sends override_manual_ids for checked rows", async () => {
    const { calls } = setupMock({
      employees: [EMP], structures: [ST], assignments: [],
      collisions: {
        employee_id: "e1",
        structure_id: "s1",
        effective_from: "2026-12-01",
        manual: [
          {
            kind: "employee_earning",
            id: "me1",
            component_kind: "earning",
            component_type_id: "et1",
            effective_from: "2026-01-01",
            effective_to: null,
            status: "requires_override",
          },
        ],
        structure_owned: [],
      },
    });
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("new-assignment-button")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("new-assignment-button"));
    fireEvent.change(screen.getByTestId("form-structure"), {
      target: { value: "s1" },
    });
    fireEvent.change(screen.getByTestId("form-effective-from"), {
      target: { value: "2026-12-01" },
    });
    fireEvent.click(screen.getByTestId("check-collisions-button"));
    await waitFor(() =>
      expect(screen.getByTestId("override-checkbox-me1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("override-checkbox-me1"));
    fireEvent.click(screen.getByTestId("submit-assignment-button"));
    await waitFor(() => {
      const post = calls.find(
        (c) =>
          c.method === "POST" &&
          c.url.endsWith("/payroll/employee-salary-assignments"),
      );
      expect(post).toBeDefined();
      const body = JSON.parse(post!.body);
      expect(body.employee_id).toBe("e1");
      expect(body.structure_id).toBe("s1");
      expect(body.effective_from).toBe("2026-12-01");
      expect(body.override_manual_ids).toEqual([
        { kind: "employee_earning", id: "me1" },
      ]);
    });
  });
});

describe("EmployeePayrollPage — approval actions", () => {
  it("shows action buttons for pending assignments", async () => {
    setupMock({ employees: [EMP], assignments: [ASSIGN_PENDING] });
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("assignment-row-a1")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("assignment-approve-a1")).toBeInTheDocument();
    expect(screen.getByTestId("assignment-reject-a1")).toBeInTheDocument();
    expect(screen.getByTestId("assignment-cancel-a1")).toBeInTheDocument();
  });

  it("does not show action buttons for non-pending assignments", async () => {
    setupMock({ employees: [EMP], assignments: [ASSIGN_APPROVED] });
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("assignment-row-a2")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("assignment-approve-a2")).toBeNull();
    expect(screen.queryByTestId("assignment-reject-a2")).toBeNull();
    expect(screen.queryByTestId("assignment-cancel-a2")).toBeNull();
  });

  it("approve confirms and posts to /approve", async () => {
    const { calls } = setupMock({
      employees: [EMP], assignments: [ASSIGN_PENDING],
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("assignment-approve-a1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("assignment-approve-a1"));
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled();
      expect(
        calls.some(
          (c) => c.method === "POST" && c.url.endsWith("/a1/approve"),
        ),
      ).toBe(true);
    });
  });

  it("approve does nothing when confirm is cancelled", async () => {
    const { calls } = setupMock({
      employees: [EMP], assignments: [ASSIGN_PENDING],
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("assignment-approve-a1")).toBeInTheDocument(),
    );
    const before = calls.filter((c) => c.method === "POST").length;
    fireEvent.click(screen.getByTestId("assignment-approve-a1"));
    await new Promise((r) => setTimeout(r, 50));
    const after = calls.filter((c) => c.method === "POST").length;
    expect(after).toBe(before);
  });

  it("reject opens a modal with required note", async () => {
    setupMock({ employees: [EMP], assignments: [ASSIGN_PENDING] });
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("assignment-reject-a1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("assignment-reject-a1"));
    const note = await screen.findByTestId("assignment-reject-note");
    expect(note).toBeInTheDocument();
    const submit = screen.getByTestId("assignment-reject-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(note, { target: { value: "wrong salary" } });
    await waitFor(() => {
      const btn = screen.getByTestId("assignment-reject-submit") as HTMLButtonElement;
      expect(btn.disabled).toBe(false);
    });
  });

  it("reject posts with note", async () => {
    const { calls } = setupMock({
      employees: [EMP], assignments: [ASSIGN_PENDING],
    });
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("assignment-reject-a1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("assignment-reject-a1"));
    await screen.findByTestId("assignment-reject-note");
    fireEvent.change(screen.getByTestId("assignment-reject-note"), {
      target: { value: "wrong salary" },
    });
    fireEvent.click(screen.getByTestId("assignment-reject-submit"));
    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.endsWith("/a1/reject"),
      );
      expect(post).toBeDefined();
      const body = JSON.parse(post!.body);
      expect(body.note).toBe("wrong salary");
    });
  });

  it("cancel confirms and posts to /cancel", async () => {
    const { calls } = setupMock({
      employees: [EMP], assignments: [ASSIGN_PENDING],
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("assignment-cancel-a1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("assignment-cancel-a1"));
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled();
      expect(
        calls.some(
          (c) => c.method === "POST" && c.url.endsWith("/a1/cancel"),
        ),
      ).toBe(true);
    });
  });

  it("surfaces backend error on approve failure", async () => {
    setupMock({
      employees: [EMP], assignments: [ASSIGN_PENDING],
      approveStatus: 409,
      approveResponse: { error: { code: "self_approval_forbidden" } },
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage("/payroll/employee-payroll/e1");
    await waitFor(() =>
      expect(screen.getByTestId("assignment-approve-a1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("assignment-approve-a1"));
    await waitFor(() =>
      expect(screen.getByTestId("assignment-action-error")).toHaveTextContent(
        /cannot approve an assignment you submitted/i,
      ),
    );
  });
});