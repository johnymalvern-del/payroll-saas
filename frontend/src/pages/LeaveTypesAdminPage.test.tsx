import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor, within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const { mockPermsRef } = vi.hoisted(() => ({
  mockPermsRef: { value: ["user_manage", "self_view"] as string[] },
}));

vi.mock("../auth/useMe", () => ({
  useMe: () => ({
    data: {
      id: "u-admin",
      username: "admin",
      role: "payroll_admin",
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

import { LeaveTypesAdminPage } from "./LeaveTypesAdminPage";

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

const TYPE_ANNUAL = {
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
  row_version: 1,
  approval_chain: ["manager", "hr"],
  requires_payroll_admin_final: false,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
};

const TYPE_SICK_INACTIVE = {
  ...TYPE_ANNUAL,
  id: "lt2",
  name: "Sick Leave",
  code: "sick",
  is_active: false,
};

function setupMock(opts: {
  activeItems?: unknown[];
  inactiveItems?: unknown[];
  nextCursor?: string | null;
  page2?: unknown[];
  activeStatus?: number;
  deactStatus?: number;
  reactStatus?: number;
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

    if (method === "POST" && url.endsWith("/deactivate")) {
      return jr({ ...TYPE_ANNUAL, is_active: false }, opts.deactStatus ?? 200);
    }
    if (method === "POST" && url.endsWith("/reactivate")) {
      return jr({ ...TYPE_SICK_INACTIVE, is_active: true }, opts.reactStatus ?? 200);
    }
    if (method === "POST" && url.endsWith("/leave/types")) {
      return jr(TYPE_ANNUAL, 201);
    }
    if (method === "PATCH") {
      return jr(TYPE_ANNUAL);
    }
    if (url.includes("/leave/types")) {
      if (url.includes("cursor=")) {
        return jr({
          items: opts.page2 ?? [],
          next_cursor: null,
        });
      }
      if (url.includes("is_active=false")) {
        return jr({
          items: opts.inactiveItems ?? [],
          next_cursor: null,
        });
      }
      return jr(
        {
          items: opts.activeItems ?? [],
          next_cursor: opts.nextCursor ?? null,
        },
        opts.activeStatus ?? 200,
      );
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/leave/types-admin"]}>
          <Routes>
            <Route
              path="/leave/types-admin"
              element={<LeaveTypesAdminPage />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

beforeEach(() => {
  mockPermsRef.value = ["user_manage", "self_view"];
  vi.restoreAllMocks();
});
afterEach(() => { cleanup(); });

describe("LeaveTypesAdminPage", () => {
  it("renders header and Create button when user_manage", async () => {
    setupMock({});
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-admin-page")).toBeInTheDocument(),
    );
    expect(screen.getByText("Leave Types", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByTestId("leave-types-create")).toBeInTheDocument();
  });

  it("shows permission alert when user lacks user_manage", async () => {
    mockPermsRef.value = ["leave_approve"];
    setupMock({});
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByTestId("leave-types-admin-no-permission"),
      ).toBeInTheDocument(),
    );
  });

  it("renders table with type data on Active tab", async () => {
    setupMock({ activeItems: [TYPE_ANNUAL] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-admin-table")).toBeInTheDocument(),
    );
    const row = screen.getByTestId("leave-types-row-lt1");
    expect(within(row).getByText("Annual Leave")).toBeInTheDocument();
    // "annual" appears twice in the row: the code cell and the
    // accrual_method cell. Assert both are present rather than asserting
    // a single unique match.
    expect(within(row).getAllByText("annual")).toHaveLength(2);
    expect(within(row).getByText(/manager → hr/)).toBeInTheDocument();
    expect(within(row).getByText("active")).toBeInTheDocument();
  });

  it("queries active types with is_active=true", async () => {
    const { calls } = setupMock({ activeItems: [TYPE_ANNUAL] });
    renderPage();
    await waitFor(() => {
      const reqs = calls.filter((c) => c.url.includes("/leave/types"));
      expect(reqs.some((c) => c.url.includes("is_active=true"))).toBe(true);
    });
  });

  it("switching to Inactive tab queries is_active=false", async () => {
    const { calls } = setupMock({
      activeItems: [TYPE_ANNUAL],
      inactiveItems: [TYPE_SICK_INACTIVE],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-row-lt1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-types-tab-inactive"));
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-row-lt2")).toBeInTheDocument(),
    );
    const reqs = calls.filter((c) => c.url.includes("/leave/types"));
    expect(reqs.some((c) => c.url.includes("is_active=false"))).toBe(true);
  });

  it("empty state on empty tab", async () => {
    setupMock({});
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-admin-empty")).toBeInTheDocument(),
    );
  });

  it("error state on fetch failure", async () => {
    setupMock({ activeStatus: 500 });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-admin-error")).toBeInTheDocument(),
    );
  });

  it("Create button opens the form modal in create mode", async () => {
    setupMock({});
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-create")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-types-create"));
    await waitFor(() =>
      expect(screen.getByTestId("leave-type-form-modal")).toBeInTheDocument(),
    );
    const code = screen.getByTestId("leave-type-form-code") as HTMLInputElement;
    expect(code).not.toBeDisabled();
  });

  it("Edit button opens the form modal with type data prefilled", async () => {
    setupMock({ activeItems: [TYPE_ANNUAL] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-row-lt1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-types-edit-lt1"));
    await waitFor(() =>
      expect(screen.getByTestId("leave-type-form-modal")).toBeInTheDocument(),
    );
    const name = screen.getByTestId("leave-type-form-name") as HTMLInputElement;
    const code = screen.getByTestId("leave-type-form-code") as HTMLInputElement;
    expect(name.value).toBe("Annual Leave");
    expect(code.value).toBe("annual");
    expect(code).toBeDisabled();
  });

  it("Deactivate confirms and POSTs to /deactivate", async () => {
    setupMock({ activeItems: [TYPE_ANNUAL] });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { calls } = setupMock({ activeItems: [TYPE_ANNUAL] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-row-lt1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-types-deactivate-lt1"));
    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.endsWith("/lt1/deactivate"),
      );
      expect(post).toBeDefined();
    });
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-action-msg")).toHaveTextContent(
        /Deactivated/i,
      ),
    );
  });

  it("Deactivate does nothing when confirm is cancelled", async () => {
    const { calls } = setupMock({ activeItems: [TYPE_ANNUAL] });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-row-lt1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-types-deactivate-lt1"));
    await new Promise((r) => setTimeout(r, 50));
    expect(
      calls.filter(
        (c) => c.method === "POST" && c.url.includes("/deactivate"),
      ).length,
    ).toBe(0);
  });

  it("Reactivate on inactive tab POSTs to /reactivate", async () => {
    setupMock({ inactiveItems: [TYPE_SICK_INACTIVE] });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { calls } = setupMock({ inactiveItems: [TYPE_SICK_INACTIVE] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-tab-inactive")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-types-tab-inactive"));
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-row-lt2")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-types-reactivate-lt2"));
    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.endsWith("/lt2/reactivate"),
      );
      expect(post).toBeDefined();
    });
  });

  it("surfaces leave_type_in_use on deactivate failure", async () => {
    setupMock({ activeItems: [TYPE_ANNUAL] });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      const method = requestMethod(input);
      if (method === "POST" && url.endsWith("/deactivate")) {
        return jr(
          {
            error: {
              code: "leave_type_in_use",
              details: { balances: 3 },
            },
          },
          409,
        );
      }
      return jr({ items: [TYPE_ANNUAL], next_cursor: null });
    }) as unknown as typeof fetch;
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-row-lt1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-types-deactivate-lt1"));
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-action-msg")).toHaveTextContent(
        /Cannot deactivate/i,
      ),
    );
  });

  it("Load more follows cursor", async () => {
    const { calls } = setupMock({
      activeItems: [TYPE_ANNUAL],
      page2: [{ ...TYPE_ANNUAL, id: "lt3", name: "Family Leave" }],
      nextCursor: "abc",
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-row-lt1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("leave-types-load-more"));
    await waitFor(() =>
      expect(screen.getByTestId("leave-types-row-lt3")).toBeInTheDocument(),
    );
    expect(calls.filter((c) => c.url.includes("cursor=abc")).length).toBe(1);
  });
});