import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor, within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { SalaryStructuresPage } from "./SalaryStructuresPage";

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
  structures?: unknown[];
  earningTypes?: unknown[];
  deductionTypes?: unknown[];
  createResponse?: unknown;
  createStatus?: number;
  deactivateResponse?: unknown;
  listStatus?: number;
  // Pagination mocks. When provided, the first call returns the first page
  // and a follow-up call whose URL includes "cursor=<cursor>" returns the
  // second page.
  listFirstPage?: { items: unknown[]; next_cursor: string | null };
  listSecondPage?: { items: unknown[]; next_cursor: string | null } | { status: number };
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

    if (
      method === "POST" &&
      /\/salary-structures\/[^/]+\/deactivate$/.test(url)
    ) {
      return jr(
        opts.deactivateResponse ??
          { deactivated: true, structure_group_id: "g1" },
      );
    }
    if (method === "POST" && url.endsWith("/payroll/salary-structures")) {
      return jr(
        opts.createResponse ?? {
          id: "s1",
          structure_group_id: "g1",
          version_number: 1,
          is_current: true,
          name: "Test",
          description: null,
          pay_basis: "monthly",
          base_rate: "10000",
          is_active: true,
          row_version: 1,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          components: [],
        },
        opts.createStatus ?? 201,
      );
    }
    if (url.includes("/payroll/earning-types")) {
      return jr({ items: opts.earningTypes ?? [] });
    }
    if (url.includes("/payroll/deduction-types")) {
      return jr({ items: opts.deductionTypes ?? [] });
    }
    if (url.includes("/payroll/salary-structures")) {
      // Pagination path
      if (opts.listFirstPage) {
        if (url.includes("cursor=")) {
          const second = opts.listSecondPage;
          if (second && "status" in second && typeof second.status === "number") {
            return jr({ error: { code: "invalid_cursor" } }, second.status);
          }
          return jr(
            (second as { items: unknown[]; next_cursor: string | null })
              ?? { items: [], next_cursor: null },
          );
        }
        return jr(opts.listFirstPage);
      }
      // Legacy path (no pagination mocks configured)
      return jr({ items: opts.structures ?? [] }, opts.listStatus ?? 200);
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <SalaryStructuresPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

const S1 = {
  id: "s1",
  structure_group_id: "g1",
  version_number: 1,
  is_current: true,
  name: "Monthly Basic",
  description: null,
  pay_basis: "monthly",
  base_rate: "18000",
  is_active: true,
  row_version: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  components: [],
};

const S2 = { ...S1, id: "s2", structure_group_id: "g2", name: "Hourly Basic" };

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("SalaryStructuresPage", () => {
  it("renders the page heading", async () => {
    setupMock({ structures: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("salary-structures-page")).toBeInTheDocument(),
    );
    expect(
      screen.getByText("Salary structures", { selector: "h2, h1, h3, h4" }),
    ).toBeInTheDocument();
  });

  it("shows empty state when no structures exist", async () => {
    setupMock({ structures: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structures-empty")).toBeInTheDocument(),
    );
  });

  it("renders the structures table when data is present", async () => {
    setupMock({ structures: [S1] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structure-row-s1")).toBeInTheDocument(),
    );
    const row = screen.getByTestId("structure-row-s1");
    expect(within(row).getByText("Monthly Basic")).toBeInTheDocument();
    expect(within(row).getByText("18000")).toBeInTheDocument();
  });

  it("shows an error alert when the list request fails", async () => {
    setupMock({ structures: [], listStatus: 500 });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structures-error")).toBeInTheDocument(),
    );
  });

  it("opens the create modal on button click", async () => {
    setupMock({ structures: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structures-empty")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("new-structure-button"));
    const nameInput = await screen.findByTestId("field-name");
    expect(nameInput).toBeInTheDocument();
    expect(screen.getByTestId("create-submit")).toBeInTheDocument();
  });

  it("submits a create with the expected body", async () => {
    const { calls } = setupMock({ structures: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structures-empty")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("new-structure-button"));
    const nameInput = await screen.findByTestId("field-name");
    fireEvent.change(nameInput, {
      target: { value: "New Structure" },
    });
    fireEvent.change(screen.getByTestId("field-base-rate"), {
      target: { value: "5000" },
    });
    fireEvent.click(screen.getByTestId("create-submit"));
    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.endsWith("/payroll/salary-structures"),
      );
      expect(post).toBeDefined();
      const body = JSON.parse(post!.body);
      expect(body.name).toBe("New Structure");
      expect(body.base_rate).toBe("5000");
      expect(body.pay_basis).toBe("monthly");
      expect(body.components).toEqual([]);
    });
  });

  it("validates that name is required", async () => {
    setupMock({ structures: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structures-empty")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("new-structure-button"));
    const submit = await screen.findByTestId("create-submit");
    fireEvent.click(submit);
    await waitFor(() =>
      expect(screen.getByTestId("draft-error")).toBeInTheDocument(),
    );
  });

  it("deactivate calls the endpoint on confirm", async () => {
    const { calls } = setupMock({ structures: [S1] });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structure-row-s1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("structure-deactivate-s1"));
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled();
      expect(
        calls.some(
          (c) => c.method === "POST" && c.url.includes("/deactivate"),
        ),
      ).toBe(true);
    });
  });

  it("deactivate does nothing on cancel", async () => {
    const { calls } = setupMock({ structures: [S1] });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structure-row-s1")).toBeInTheDocument(),
    );
    const before = calls.filter((c) => c.method === "POST").length;
    fireEvent.click(screen.getByTestId("structure-deactivate-s1"));
    await new Promise((r) => setTimeout(r, 50));
    const after = calls.filter((c) => c.method === "POST").length;
    expect(after).toBe(before);
  });

  it("adding an earning component renders a component row", async () => {
    setupMock({ structures: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structures-empty")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("new-structure-button"));
    const addBtn = await screen.findByTestId("add-earning");
    fireEvent.click(addBtn);
    await waitFor(() =>
      expect(screen.getByTestId("component-row-0")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("component-amount-0")).toBeInTheDocument();
    expect(screen.getByTestId("component-rate-0")).toBeInTheDocument();
  });

  // ---- pagination (M3.5 item 3) ----

  it("hides load-more when next_cursor is null", async () => {
    setupMock({ structures: [S1] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structure-row-s1")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("structures-load-more")).toBeNull();
  });

  it("load-more fetches the next page and appends items", async () => {
    const { calls } = setupMock({
      listFirstPage: { items: [S1], next_cursor: "abc" },
      listSecondPage: { items: [S2], next_cursor: null },
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structure-row-s1")).toBeInTheDocument(),
    );
    const loadMore = await screen.findByTestId("structures-load-more");
    fireEvent.click(loadMore);
    await waitFor(() =>
      expect(screen.getByTestId("structure-row-s2")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("structure-row-s1")).toBeInTheDocument();
    // Exactly one follow-up request carried cursor=abc
    const withCursor = calls.filter((c) => c.url.includes("cursor=abc"));
    expect(withCursor.length).toBe(1);
    // After the second page, load-more is gone.
    await waitFor(() =>
      expect(screen.queryByTestId("structures-load-more")).toBeNull(),
    );
  });

  it("surfaces an error when the next page fails", async () => {
    setupMock({
      listFirstPage: { items: [S1], next_cursor: "abc" },
      listSecondPage: { status: 400 },
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structure-row-s1")).toBeInTheDocument(),
    );
    const loadMore = await screen.findByTestId("structures-load-more");
    fireEvent.click(loadMore);
    await waitFor(() =>
      expect(screen.getByTestId("structures-load-more-error")).toBeInTheDocument(),
    );
  });
});