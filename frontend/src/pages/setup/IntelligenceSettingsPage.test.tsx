import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter } from "react-router-dom";
import { IntelligenceSettingsPage } from "./IntelligenceSettingsPage";

const hoisted = vi.hoisted(() => ({
  permissions: ["intelligence_view", "intelligence_manage"] as string[],
}));

vi.mock("../../auth/useMe", () => ({
  useMe: () => ({
    data: {
      id: "u1", username: "admin", role: "payroll_admin",
      employee_id: null,
      permissions: hoisted.permissions,
      must_change_password: false, default_timezone: "Africa/Johannesburg",
    },
    isLoading: false, isError: false,
  }),
}));

function jr(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
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
        <MemoryRouter initialEntries={["/setup/intelligence"]}>
          <IntelligenceSettingsPage />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const SETTINGS = {
  id: "s1", default_mode: "traditional",
  acknowledged_at: null, acknowledged_by_user_id: null, row_version: 1,
};

const WORKFLOWS = {
  items: [
    { workflow: "leave_decision", company_default: "traditional", override_mode: null,
      override_active: false, effective_mode: "traditional",
      row_version: null, effective_from: null,
      autonomous_capability_implemented: false },
  ],
};

const CHANGELOG = { items: [] };

function mockAll(extra?: (url: string, method: string) => Response | null) {
  global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = urlOf(input);
    const method = init?.method ?? "GET";
    if (extra) {
      const r = extra(url, method);
      if (r) return r;
    }
    if (url.includes("/intelligence/settings/workflows")) return jr(WORKFLOWS);
    if (url.includes("/intelligence/settings/change-log")) return jr(CHANGELOG);
    if (url.includes("/intelligence/settings")) return jr(SETTINGS);
    return jr({});
  });
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("IntelligenceSettingsPage", () => {
  it("loads current mode and shows three choices", async () => {
    mockAll();
    renderPage();
    await waitFor(() => expect(screen.getByTestId("intel-company-mode")).toBeInTheDocument());
    expect(screen.getByText("Traditional / Manual")).toBeInTheDocument();
    expect(screen.getByText("Assisted")).toBeInTheDocument();
    expect(screen.getByText("Autonomous")).toBeInTheDocument();
  });

  it("shows workflow overrides table", async () => {
    mockAll();
    renderPage();
    await waitFor(() => expect(screen.getByTestId("intel-workflows-table")).toBeInTheDocument());
    expect(screen.getByText(/leave decision/)).toBeInTheDocument();
  });

  it("requires reason before enabling save", async () => {
    mockAll();
    renderPage();
    await waitFor(() => expect(screen.getByTestId("intel-save")).toBeInTheDocument());
    expect(screen.getByTestId("intel-save")).toBeDisabled();
  });

  it("Save is disabled when mode unchanged", async () => {
    mockAll();
    renderPage();
    await waitFor(() => expect(screen.getByTestId("intel-save")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("intel-reason"), { target: { value: "test reason" } });
    expect(screen.getByTestId("intel-save")).toBeDisabled();
  });

  it("saves assisted mode with reason", async () => {
    mockAll((url, method) => {
      if (method === "PATCH" && url.includes("/settings/default-mode")) {
        return jr({ ...SETTINGS, default_mode: "assisted", row_version: 2 });
      }
      return null;
    });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("intel-company-mode")).toBeInTheDocument());
    // SegmentedControl is a radio-group; use label text
    fireEvent.click(screen.getByText("Assisted"));
    fireEvent.change(screen.getByTestId("intel-reason"), { target: { value: "moving to assisted" } });
    await waitFor(() => expect(screen.getByTestId("intel-save")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("intel-save"));
    await waitFor(() => {
      const calls = (global.fetch as unknown as { mock: { calls: [RequestInfo|URL, RequestInit?][] } }).mock.calls;
      const patch = calls.find(([i, init]) =>
        init?.method === "PATCH" && urlOf(i).includes("/settings/default-mode"),
      );
      expect(patch).toBeDefined();
      const body = JSON.parse((patch![1] as RequestInit).body as string);
      expect(body.default_mode).toBe("assisted");
      expect(body.reason).toBe("moving to assisted");
      expect(body.acknowledged_autonomous).toBe(false);
    });
  });

  it("Autonomous requires acknowledgement modal", async () => {
    mockAll((url, method) => {
      if (method === "PATCH" && url.includes("/settings/default-mode")) {
        return jr({ ...SETTINGS, default_mode: "autonomous", acknowledged_at: "2026-11-06T00:00:00Z", row_version: 2 });
      }
      return null;
    });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("intel-company-mode")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Autonomous"));
    fireEvent.change(screen.getByTestId("intel-reason"), { target: { value: "trial autonomous" } });
    await waitFor(() => expect(screen.getByTestId("intel-save")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("intel-save"));
    // Modal should open
    await waitFor(() => expect(screen.getByText("Confirm Autonomous mode")).toBeInTheDocument());
  });

  it("permission denied hides write controls", async () => {
    hoisted.permissions = ["intelligence_view"];
    mockAll();
    renderPage();
    await waitFor(() => expect(screen.getByTestId("intel-readonly-notice")).toBeInTheDocument());
    expect(screen.getByTestId("intel-save")).toBeDisabled();
    hoisted.permissions = ["intelligence_view", "intelligence_manage"];
  });

});
