import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { ExceptionsPage } from "./ExceptionsPage";

function jr(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  if (typeof Request !== "undefined" && input instanceof Request) {
    return input.url;
  }
  return String(input);
}

function requestMethod(input: RequestInfo | URL): string {
  if (typeof Request !== "undefined" && input instanceof Request) {
    return input.method;
  }
  return "GET";
}

type Call = { url: string; method: string; body: string };

function setupMock(opts: {
  exceptions?: unknown[];
  employees?: unknown[];
  resolveResponse?: unknown;
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
      url.includes("/attendance/exceptions/") &&
      url.includes("/resolve")
    ) {
      return jr(
        opts.resolveResponse ?? {
          exception: {},
          adjustment_id: null,
          day_status: null,
        },
      );
    }
    if (url.includes("/attendance/exceptions")) {
      return jr({ items: opts.exceptions ?? [], next_cursor: null });
    }

    if (url.includes("/attendance/reason-codes")) {
      return jr({ items: [
        { code: "system_correction", label: "System correction", requires_note: false },
        { code: "other", label: "Other", requires_note: true },
      ] });
    }
    if (url.includes("/api/v1/employees")) {
      return jr({ items: opts.employees ?? [], next_cursor: null });
    }
    return jr({}, 200);
  }) as unknown as typeof fetch;
  return { calls };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <ExceptionsPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

const EMP = {
  id: "e1",
  employee_code: "EMP001",
  first_name: "Ada",
  last_name: "Lovelace",
};

const EXC = {
  id: "exc1",
  employee_id: "e1",
  work_date: "2026-10-15",
  type: "missing_out",
  source_ref: { punch_id: "p1" },
  suggested_fix: {
    outcome: "worked",
    time_in: "2026-10-15T08:00:00Z",
    time_out: "2026-10-15T16:30:00Z",
    reason_code: "missing_out",
  },
  status: "open",
  assigned_to: null,
  resolved_by: null,
  resolved_at: null,
  resolution: null,
  created_at: "2026-10-16T00:00:00Z",
  updated_at: "2026-10-16T00:00:00Z",
};

const EXC2 = { ...EXC, id: "exc2" };

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ExceptionsPage", () => {
  beforeEach(() => setupMock({ exceptions: [EXC], employees: [EMP] }));

  it("renders the title, exception row, and employee name", async () => {
    renderPage();
    expect(screen.getByText("Exceptions")).toBeInTheDocument();
    const row = await screen.findByTestId("exception-exc1");
    expect(row).toBeInTheDocument();
    expect(within(row).getByText(/missing out/i)).toBeInTheDocument();
    expect(within(row).getByText(/Ada Lovelace/)).toBeInTheDocument();
    expect(within(row).getByText(/EMP001/)).toBeInTheDocument();
  });

  it("shows empty text when no exceptions", async () => {
    setupMock({ exceptions: [], employees: [EMP] });
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText(/no exceptions match the current filters/i),
      ).toBeInTheDocument();
    });
  });

  it("shows error state when fetch fails", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.includes("/attendance/exceptions")) {
        return jr({ error: { code: "boom" } }, 500);
      }
      return jr({ items: [], next_cursor: null });
    }) as unknown as typeof fetch;
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/could not load exceptions/i)).toBeInTheDocument();
    });
  });

  it("never sends type= on the exceptions request (client-side filter)", async () => {
    const { calls } = setupMock({ exceptions: [EXC], employees: [EMP] });
    renderPage();
    await screen.findByTestId("exception-exc1");
    const excCalls = calls.filter((c) =>
      c.url.includes("/attendance/exceptions"),
    );
    expect(excCalls.length).toBeGreaterThan(0);
    expect(excCalls.every((c) => !c.url.includes("type="))).toBe(true);
  });

  it("apply suggestion asks for confirmation and does not POST when cancelled", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { calls } = setupMock({ exceptions: [EXC], employees: [EMP] });
    renderPage();
    const applyBtn = await screen.findByTestId("apply-exc1");
    fireEvent.click(applyBtn);
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled();
    });
    expect(calls.filter((c) => c.method === "POST").length).toBe(0);
  });

  it("apply suggestion POSTs resolve with action=apply_suggestion on confirm", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { calls } = setupMock({
      exceptions: [EXC],
      employees: [EMP],
      resolveResponse: {
        exception: EXC,
        adjustment_id: "adj1",
        day_status: "worked",
      },
    });
    renderPage();
    const applyBtn = await screen.findByTestId("apply-exc1");
    fireEvent.click(applyBtn);
    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.includes("/resolve"),
      );
      expect(post).toBeTruthy();
      const parsed = JSON.parse(post!.body) as { action: string };
      expect(parsed.action).toBe("apply_suggestion");
    });
  });

  it("direct apply surfaces day_locked at page level", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      const method = requestMethod(input);
      if (method === "POST" && url.includes("/resolve")) {
        return jr({ error: { code: "day_locked" } }, 409);
      }
      if (url.includes("/attendance/exceptions")) {
        return jr({ items: [EXC], next_cursor: null });
      }
  
    if (url.includes("/attendance/reason-codes")) {
      return jr({ items: [
        { code: "system_correction", label: "System correction", requires_note: false },
        { code: "other", label: "Other", requires_note: true },
      ] });
    }
    if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;
    renderPage();
    fireEvent.click(await screen.findByTestId("apply-exc1"));
    const alert = await screen.findByTestId("direct-error");
    expect(alert).toBeInTheDocument();
    expect((alert.textContent ?? "").length).toBeGreaterThan(0);
  });

  it("direct apply surfaces cannot_adjust_own at page level", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      const method = requestMethod(input);
      if (method === "POST" && url.includes("/resolve")) {
        return jr({ error: { code: "cannot_adjust_own" } }, 403);
      }
      if (url.includes("/attendance/exceptions")) {
        return jr({ items: [EXC], next_cursor: null });
      }
  
    if (url.includes("/attendance/reason-codes")) {
      return jr({ items: [
        { code: "system_correction", label: "System correction", requires_note: false },
        { code: "other", label: "Other", requires_note: true },
      ] });
    }
    if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;
    renderPage();
    fireEvent.click(await screen.findByTestId("apply-exc1"));
    const alert = await screen.findByTestId("direct-error");
    expect(alert).toBeInTheDocument();
    expect((alert.textContent ?? "").length).toBeGreaterThan(0);
  });

  it("employees failure shows an error with a working retry", async () => {
    let employeeCalls = 0;
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
  
    if (url.includes("/attendance/reason-codes")) {
      return jr({ items: [
        { code: "system_correction", label: "System correction", requires_note: false },
        { code: "other", label: "Other", requires_note: true },
      ] });
    }
    if (url.includes("/api/v1/employees")) {
        employeeCalls += 1;
        if (employeeCalls === 1) {
          return jr({ error: { code: "boom" } }, 500);
        }
        return jr({ items: [EMP], next_cursor: null });
      }
      if (url.includes("/attendance/exceptions")) {
        return jr({ items: [EXC], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;
    renderPage();
    const err = await screen.findByTestId("employees-error");
    expect(err).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("employees-retry"));
    await waitFor(() => {
      expect(screen.queryByTestId("employees-error")).not.toBeInTheDocument();
    });
  });

  it("custom button opens modal with adjustment form", async () => {
    renderPage();
    const customBtn = await screen.findByTestId("custom-exc1");
    fireEvent.click(customBtn);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("adj-submit")).toBeInTheDocument();
    expect(within(dialog).getByTestId("adj-reason")).toBeInTheDocument();
  });

  it("dismiss requires a note of at least 3 characters", async () => {
    renderPage();
    const dismissBtn = await screen.findByTestId("dismiss-exc1");
    fireEvent.click(dismissBtn);
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByTestId("dismiss-submit"));
    await waitFor(() => {
      const alert = within(dialog).getByRole("alert");
      expect(alert).toHaveTextContent(/note of at least 3 characters/i);
    });
  });

  it("adjustment form rejects 'other' reason with a short note", async () => {
    renderPage();
    const customBtn = await screen.findByTestId("custom-exc1");
    fireEvent.click(customBtn);
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => {
      const el = within(dialog).getByTestId("adj-reason") as HTMLInputElement;
      expect(el.disabled).toBe(false);
    });
    fireEvent.click(within(dialog).getByTestId("adj-reason"));
    fireEvent.click(await screen.findByText("Other"));
    fireEvent.change(within(dialog).getByTestId("adj-note"), {
      target: { value: "short" },
    });
    fireEvent.click(within(dialog).getByTestId("adj-submit"));
    await waitFor(() => {
      const alert = within(dialog).getByRole("alert");
      expect(alert).toHaveTextContent(/at least 10 characters/i);
    });
  });

  it("Load more follows next_cursor and appends items", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.includes("/attendance/exceptions")) {
        if (url.includes("cursor=abc")) {
          return jr({
            items: [
              { ...EXC, id: "exc2" },
              { ...EXC, id: "exc3" },
            ],
            next_cursor: null,
          });
        }
        return jr({ items: [EXC], next_cursor: "abc" });
      }
  
    if (url.includes("/attendance/reason-codes")) {
      return jr({ items: [
        { code: "system_correction", label: "System correction", requires_note: false },
        { code: "other", label: "Other", requires_note: true },
      ] });
    }
    if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;
    renderPage();
    await screen.findByTestId("exception-exc1");
    expect(screen.queryByTestId("exception-exc2")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("exceptions-load-more"));
    await screen.findByTestId("exception-exc2");
    expect(screen.getByTestId("exception-exc3")).toBeInTheDocument();
  });

  it("bulk dry run renders per-row results and enables confirm", async () => {
    const { calls } = setupMock({ exceptions: [EXC, EXC2], employees: [EMP] });
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
      if (url.includes("/bulk_resolve")) {
        const parsed = JSON.parse(body) as {
          items: { exception_id: string }[];
          token?: string;
        };
        const results = parsed.items.map((it, i) => ({
          index: i,
          exception_id: it.exception_id,
          ok: true,
        }));
        return jr({
          results,
          applied: 0,
          dry_run: true,
          token: "T1",
        });
      }
      if (url.includes("/attendance/exceptions")) {
        return jr({ items: [EXC, EXC2], next_cursor: null });
      }
  
    if (url.includes("/attendance/reason-codes")) {
      return jr({ items: [
        { code: "system_correction", label: "System correction", requires_note: false },
        { code: "other", label: "Other", requires_note: true },
      ] });
    }
    if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await screen.findByTestId("exception-exc1");
    fireEvent.click(screen.getByTestId("exceptions-bulk-toggle"));
    fireEvent.click(await screen.findByTestId("exceptions-bulk-select-all"));
    fireEvent.click(screen.getByTestId("exceptions-bulk-dry-run"));

    await screen.findByTestId("exceptions-bulk-results");
    expect(screen.getByTestId("exceptions-bulk-row-0")).toBeInTheDocument();
    expect(screen.getByTestId("exceptions-bulk-row-1")).toBeInTheDocument();
    const confirmBtn = screen.getByTestId(
      "exceptions-bulk-confirm",
    ) as HTMLButtonElement;
    await waitFor(() => expect(confirmBtn.disabled).toBe(false));
  });

  it("bulk confirm sends dry-run token and shows applied count", async () => {
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
      if (url.includes("/bulk_resolve")) {
        const parsed = JSON.parse(body) as {
          items: { exception_id: string }[];
          token?: string;
        };
        const results = parsed.items.map((it, i) => ({
          index: i,
          exception_id: it.exception_id,
          ok: true,
          adjustment_id: `adj-${i}`,
        }));
        return jr({
          results,
          applied: parsed.token ? results.length : 0,
          dry_run: !parsed.token,
          token: "T1",
        });
      }
      if (url.includes("/attendance/exceptions")) {
        return jr({ items: [EXC], next_cursor: null });
      }
  
    if (url.includes("/attendance/reason-codes")) {
      return jr({ items: [
        { code: "system_correction", label: "System correction", requires_note: false },
        { code: "other", label: "Other", requires_note: true },
      ] });
    }
    if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await screen.findByTestId("exception-exc1");
    fireEvent.click(screen.getByTestId("exceptions-bulk-toggle"));
    fireEvent.click(await screen.findByTestId("exception-select-exc1"));
    fireEvent.click(screen.getByTestId("exceptions-bulk-dry-run"));
    await screen.findByTestId("exceptions-bulk-results");

    fireEvent.click(screen.getByTestId("exceptions-bulk-confirm"));
    fireEvent.click(await screen.findByTestId("exceptions-bulk-confirm-apply"));

    await waitFor(() => {
      const posts = calls.filter(
        (c) => c.method === "POST" && c.url.includes("/bulk_resolve"),
      );
      expect(posts.length).toBeGreaterThanOrEqual(2);
      const confirmPost = posts[posts.length - 1];
      const parsed = JSON.parse(confirmPost.body) as { token?: string };
      expect(parsed.token).toBe("T1");
    });
  });

  it("bulk confirm surfaces token_mismatch as mapped error", async () => {
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
      if (url.includes("/bulk_resolve")) {
        const parsed = JSON.parse(body) as {
          items: { exception_id: string }[];
          token?: string;
        };
        if (parsed.token) {
          return jr({ error: { code: "token_mismatch" } }, 409);
        }
        const results = parsed.items.map((it, i) => ({
          index: i,
          exception_id: it.exception_id,
          ok: true,
        }));
        return jr({
          results,
          applied: 0,
          dry_run: true,
          token: "T1",
        });
      }
      if (url.includes("/attendance/exceptions")) {
        return jr({ items: [EXC], next_cursor: null });
      }
  
    if (url.includes("/attendance/reason-codes")) {
      return jr({ items: [
        { code: "system_correction", label: "System correction", requires_note: false },
        { code: "other", label: "Other", requires_note: true },
      ] });
    }
    if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await screen.findByTestId("exception-exc1");
    fireEvent.click(screen.getByTestId("exceptions-bulk-toggle"));
    fireEvent.click(await screen.findByTestId("exception-select-exc1"));
    fireEvent.click(screen.getByTestId("exceptions-bulk-dry-run"));
    await screen.findByTestId("exceptions-bulk-results");

    fireEvent.click(screen.getByTestId("exceptions-bulk-confirm"));
    fireEvent.click(await screen.findByTestId("exceptions-bulk-confirm-apply"));

    const err = await screen.findByTestId("exceptions-bulk-error");
    expect(err.textContent ?? "").toMatch(/re-run the dry run/i);
  });

  it("bulk dry run surfaces per-row cannot_adjust_own without enabling confirm", async () => {
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
      if (url.includes("/bulk_resolve")) {
        const parsed = JSON.parse(body) as {
          items: { exception_id: string }[];
        };
        const results = parsed.items.map((it, i) => ({
          index: i,
          exception_id: it.exception_id,
          ok: false,
          error_code: "cannot_adjust_own",
          error_message: "A user cannot adjust their own attendance",
        }));
        return jr({
          results,
          applied: 0,
          dry_run: true,
          token: "T1",
        });
      }
      if (url.includes("/attendance/exceptions")) {
        return jr({ items: [EXC], next_cursor: null });
      }
  
    if (url.includes("/attendance/reason-codes")) {
      return jr({ items: [
        { code: "system_correction", label: "System correction", requires_note: false },
        { code: "other", label: "Other", requires_note: true },
      ] });
    }
    if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await screen.findByTestId("exception-exc1");
    fireEvent.click(screen.getByTestId("exceptions-bulk-toggle"));
    fireEvent.click(await screen.findByTestId("exception-select-exc1"));
    fireEvent.click(screen.getByTestId("exceptions-bulk-dry-run"));

    const row = await screen.findByTestId("exceptions-bulk-row-0");
    // Actual mapping for cannot_adjust_own is "You cannot adjust your own
    // attendance." — assert on the invariant prefix rather than "own record".
    expect(row.textContent ?? "").toMatch(/cannot adjust your own/i);
    const confirmBtn = screen.getByTestId(
      "exceptions-bulk-confirm",
    ) as HTMLButtonElement;
    expect(confirmBtn.disabled).toBe(true);
  });
});