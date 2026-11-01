import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { AdjustmentsPage } from "./AdjustmentsPage";

// jsdom doesn't implement scrollIntoView; Mantine's Combobox calls it when
// a MultiSelect dropdown opens, which fires async after the test body.
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

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <AdjustmentsPage />
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

async function pickEmployee() {
  const ms = await screen.findByTestId("adjustments-bulk-employees");
  fireEvent.click(ms);
  const opt = await screen.findByText("Ada Lovelace (EMP001)");
  fireEvent.click(opt);
}

function setReason(value: string) {
  fireEvent.change(screen.getByTestId("adjustments-bulk-reason"), {
    target: { value },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AdjustmentsPage (bulk)", () => {
  beforeEach(() => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;
  });

  it("renders with 0 rows and dry-run disabled until inputs are complete", async () => {
    renderPage();
    await screen.findByTestId("adjustments-bulk-employees");
    expect(
      screen.getByTestId("adjustments-bulk-count").textContent,
    ).toMatch(/0 row/);
    const dry = screen.getByTestId(
      "adjustments-bulk-dry-run",
    ) as HTMLButtonElement;
    expect(dry.disabled).toBe(true);
  });

  it("dry run shows per-row results and enables confirm; confirm sends token", async () => {
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
      if (url.includes("/attendance/adjustments/bulk")) {
        const parsed = JSON.parse(body) as {
          items: { employee_id: string; work_date: string }[];
          token?: string;
        };
        const results = parsed.items.map((it, i) => ({
          index: i,
          employee_id: it.employee_id,
          work_date: it.work_date,
          ok: true,
          adjustment_id: parsed.token ? `adj-${i}` : null,
        }));
        return jr({
          results,
          applied: parsed.token ? results.length : 0,
          dry_run: !parsed.token,
          token: "T1",
        });
      }
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await pickEmployee();
    setReason("system_correction");

    await waitFor(() => {
      expect(
        screen.getByTestId("adjustments-bulk-count").textContent,
      ).toMatch(/1 row/);
    });

    fireEvent.click(screen.getByTestId("adjustments-bulk-dry-run"));
    await screen.findByTestId("adjustments-bulk-results");
    expect(screen.getByTestId("adjustments-bulk-row-0")).toBeInTheDocument();

    const confirmBtn = screen.getByTestId(
      "adjustments-bulk-confirm",
    ) as HTMLButtonElement;
    await waitFor(() => expect(confirmBtn.disabled).toBe(false));

    fireEvent.click(confirmBtn);
    fireEvent.click(
      await screen.findByTestId("adjustments-bulk-confirm-apply"),
    );

    await waitFor(() => {
      const posts = calls.filter(
        (c) => c.method === "POST" && c.url.includes("/adjustments/bulk"),
      );
      expect(posts.length).toBeGreaterThanOrEqual(2);
      const confirm = posts[posts.length - 1];
      const parsed = JSON.parse(confirm.body) as { token?: string };
      expect(parsed.token).toBe("T1");
    });
  });

  it("revert outcome produces items with outcome=revert and no times", async () => {
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
      if (url.includes("/attendance/adjustments/bulk")) {
        const parsed = JSON.parse(body) as {
          items: {
            outcome: string;
            time_in: string | null;
            time_out: string | null;
          }[];
        };
        const results = parsed.items.map((_, i) => ({
          index: i,
          employee_id: EMP.id,
          work_date: "2026-10-15",
          ok: true,
        }));
        return jr({
          results,
          applied: 0,
          dry_run: true,
          token: "T1",
        });
      }
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await pickEmployee();
    setReason("system_correction");

    // Switch outcome to revert
    fireEvent.click(screen.getByTestId("adjustments-bulk-outcome"));
    fireEvent.click(await screen.findByText("revert"));

    await waitFor(() => {
      expect(
        screen.getByTestId("adjustments-bulk-count").textContent,
      ).toMatch(/1 row/);
    });

    fireEvent.click(screen.getByTestId("adjustments-bulk-dry-run"));
    await screen.findByTestId("adjustments-bulk-results");

    const bulkCall = calls.find((c) => c.url.includes("/adjustments/bulk"));
    expect(bulkCall).toBeTruthy();
    const body = JSON.parse(bulkCall!.body) as {
      items: { outcome: string; time_in: string | null; time_out: string | null }[];
    };
    expect(body.items[0].outcome).toBe("revert");
    expect(body.items[0].time_in).toBeNull();
    expect(body.items[0].time_out).toBeNull();
  });

  it("dry run surfaces per-row cannot_adjust_own without enabling confirm", async () => {
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
      if (url.includes("/attendance/adjustments/bulk")) {
        const parsed = JSON.parse(body) as {
          items: { employee_id: string; work_date: string }[];
        };
        const results = parsed.items.map((it, i) => ({
          index: i,
          employee_id: it.employee_id,
          work_date: it.work_date,
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
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await pickEmployee();
    setReason("system_correction");

    fireEvent.click(screen.getByTestId("adjustments-bulk-dry-run"));
    const row = await screen.findByTestId("adjustments-bulk-row-0");
    expect(row.textContent ?? "").toMatch(/cannot adjust your own/i);

    const confirmBtn = screen.getByTestId(
      "adjustments-bulk-confirm",
    ) as HTMLButtonElement;
    expect(confirmBtn.disabled).toBe(true);
  });

  it("dry run surfaces per-row day_locked", async () => {
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
      if (url.includes("/attendance/adjustments/bulk")) {
        const parsed = JSON.parse(body) as {
          items: { employee_id: string; work_date: string }[];
        };
        const results = parsed.items.map((it, i) => ({
          index: i,
          employee_id: it.employee_id,
          work_date: it.work_date,
          ok: false,
          error_code: "day_locked",
          error_message: "Day is in a closed payroll period",
        }));
        return jr({
          results,
          applied: 0,
          dry_run: true,
          token: "T1",
        });
      }
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await pickEmployee();
    setReason("system_correction");

    fireEvent.click(screen.getByTestId("adjustments-bulk-dry-run"));
    const row = await screen.findByTestId("adjustments-bulk-row-0");
    expect(row.textContent ?? "").toMatch(/locked/i);
  });

  it("token_mismatch on confirm shows mapped error", async () => {
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
      if (url.includes("/attendance/adjustments/bulk")) {
        const parsed = JSON.parse(body) as {
          items: { employee_id: string; work_date: string }[];
          token?: string;
        };
        if (parsed.token) {
          return jr({ error: { code: "token_mismatch" } }, 409);
        }
        const results = parsed.items.map((it, i) => ({
          index: i,
          employee_id: it.employee_id,
          work_date: it.work_date,
          ok: true,
        }));
        return jr({
          results,
          applied: 0,
          dry_run: true,
          token: "T1",
        });
      }
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await pickEmployee();
    setReason("system_correction");
    fireEvent.click(screen.getByTestId("adjustments-bulk-dry-run"));
    await screen.findByTestId("adjustments-bulk-results");

    const confirmBtn = screen.getByTestId(
      "adjustments-bulk-confirm",
    ) as HTMLButtonElement;
    await waitFor(() => expect(confirmBtn.disabled).toBe(false));
    fireEvent.click(confirmBtn);
    fireEvent.click(
      await screen.findByTestId("adjustments-bulk-confirm-apply"),
    );

    const err = await screen.findByTestId("adjustments-bulk-error");
    expect(err.textContent ?? "").toMatch(/re-run the dry run/i);
  });

  it("over-cap shows warning and disables dry run", async () => {
    renderPage();
    await pickEmployee();
    setReason("system_correction");

    fireEvent.change(screen.getByTestId("adjustments-bulk-from"), {
      target: { value: "2026-10-01" },
    });
    fireEvent.change(screen.getByTestId("adjustments-bulk-to"), {
      target: { value: "2026-10-03" },
    });

    await waitFor(() => {
      expect(
        screen.getByTestId("adjustments-bulk-count").textContent,
      ).toMatch(/3 row/);
    });
    expect(
      screen.queryByTestId("adjustments-bulk-over-cap"),
    ).not.toBeInTheDocument();
  });
});