import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter } from "react-router-dom";
import { IntelligenceDecisionsPage } from "./IntelligenceDecisionsPage";

vi.mock("../auth/useMe", () => ({
  useMe: () => ({
    data: {
      id: "u1", username: "admin", role: "payroll_admin",
      employee_id: null,
      permissions: ["intelligence_view", "intelligence_manage"],
      must_change_password: false, default_timezone: null,
    },
    isLoading: false, isError: false,
  }),
}));

function jr(body: unknown, s = 200): Response {
  return new Response(JSON.stringify(body), {
    status: s, headers: { "Content-Type": "application/json" },
  });
}
function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  if (input instanceof Request) return input.url;
  return String(input);
}
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <MemoryRouter initialEntries={["/intelligence/decisions"]}>
          <IntelligenceDecisionsPage />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const DECISION = {
  id: "d1", employee_id: "e1", workflow: "leave_decision",
  source_type: "leave_request", source_id: "s1",
  decision_type: "recommendation", initiator_type: "human",
  initiator_user_id: "u1",
  company_default_mode: "traditional", effective_workflow_mode: "traditional",
  workflow_override_mode: null, execution_status: "pending",
  created_at: "2026-11-07T09:00:00Z",
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("IntelligenceDecisionsPage", () => {
  it("renders empty state when no records", async () => {
    global.fetch = vi.fn(async () => jr({ items: [], next_cursor: null, total: null }));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/No decision records yet/i)).toBeInTheDocument(),
    );
  });

  it("renders a row for each decision", async () => {
    global.fetch = vi.fn(async () => jr({ items: [DECISION], next_cursor: null }));
    renderPage();
    await waitFor(() => expect(screen.getByTestId("decisions-table")).toBeInTheDocument());
    expect(screen.getByText("leave_decision")).toBeInTheDocument();
  });

  it("filters trigger refetch with workflow param", async () => {
    const calls: string[] = [];
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const u = urlOf(input);
      calls.push(u);
      return jr({ items: [DECISION], next_cursor: null });
    });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("decisions-filter-workflow")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("decisions-filter-workflow"), {
      target: { value: "leave_decision" },
    });
    await waitFor(() => {
      expect(calls.some((u) => u.includes("workflow=leave_decision"))).toBe(true);
    }, { timeout: 1500 });
  });

  it("opens drawer and shows snapshot on View", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const u = urlOf(input);
      if (u.includes("/decisions/d1/verify")) return jr({ valid: true, decision_id: "d1" });
      if (u.includes("/decisions/d1")) {
        return jr({
          ...DECISION,
          policy_version: null, statutory_version: null,
          recommendation: { action: "approve" },
          explanation: "Sufficient balance",
          audit_id: "a1",
          evidence_snapshot_id: "snap1",
          snapshot: {
            id: "snap1", decision_id: "d1",
            created_at: "2026-11-07T09:00:00Z",
            schema_version: 1,
            payload: { days: 2 },
            sha256_hex: "abc123",
          },
        });
      }
      return jr({ items: [DECISION], next_cursor: null });
    });
    renderPage();
    await waitFor(() => expect(screen.getByText("leave_decision")).toBeInTheDocument());
    fireEvent.click(screen.getByText("View"));
    await waitFor(() => {
      expect(screen.getByText(/Snapshot integrity verified/i)).toBeInTheDocument();
    }, { timeout: 1500 });
  });
});
