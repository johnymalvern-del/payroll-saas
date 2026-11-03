import { afterEach, describe, expect, it, vi } from "vitest";
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
import { MemoryRouter } from "react-router-dom";
import { PayPeriodsPage } from "./PayPeriodsPage";

if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {};
}

const MODAL_TEST_TIMEOUT_MS = 20000;

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

const PERIOD = {
  id: "pp1",
  period_key: "2026-01",
  start_date: "2026-01-01",
  end_date: "2026-01-31",
  pay_date: "2026-02-05",
  status: "open",
  cutoff_at: "2026-01-31T23:59:00+00:00",
  row_version: 1,
};

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <PayPeriodsPage />
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PayPeriodsPage", () => {
  it("renders list with period key and status", async () => {
    global.fetch = vi.fn(async () =>
      jr({ items: [PERIOD], next_cursor: null }),
    ) as unknown as typeof fetch;

    renderPage();
    const row = await screen.findByTestId("pay-period-pp1");
    expect(within(row).getByText("2026-01")).toBeInTheDocument();
    expect(within(row).getByText("open")).toBeInTheDocument();
  });

  it("shows empty state", async () => {
    global.fetch = vi.fn(async () =>
      jr({ items: [], next_cursor: null }),
    ) as unknown as typeof fetch;

    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/no pay periods yet/i)).toBeInTheDocument();
    });
  });

  it("shows load error with retry", async () => {
    let calls = 0;
    global.fetch = vi.fn(async () => {
      calls += 1;
      if (calls === 1) return jr({ error: { code: "boom" } }, 500);
      return jr({ items: [PERIOD], next_cursor: null });
    }) as unknown as typeof fetch;

    renderPage();
    await screen.findByTestId("pay-periods-load-error");
    fireEvent.click(screen.getByTestId("pay-periods-retry"));
    await screen.findByTestId("pay-period-pp1");
  });

  it(
    "create modal validates required fields then submits",
    async () => {
      const calls: { url: string; method: string; body: string }[] = [];
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        const method = requestMethod(input);
        let body = "";
        if (method !== "GET" && input instanceof Request) {
          body = await input.clone().text();
        }
        calls.push({ url, method, body });
        if (method === "POST" && url.endsWith("/payroll/pay-periods")) {
          return jr(PERIOD, 201);
        }
        return jr({ items: [], next_cursor: null });
      }) as unknown as typeof fetch;

      renderPage();
      fireEvent.click(await screen.findByTestId("pay-periods-new"));
      await screen.findByTestId("pay-periods-create-modal");

      fireEvent.click(await screen.findByTestId("pay-periods-create-submit"));
      await waitFor(() => {
        expect(
          screen.getByTestId("pay-periods-create-error").textContent ?? "",
        ).toMatch(/period key/i);
      });

      fireEvent.change(await screen.findByTestId("pay-periods-create-key"), {
        target: { value: "2026-02" },
      });
      fireEvent.change(await screen.findByTestId("pay-periods-create-start"), {
        target: { value: "2026-02-01" },
      });
      fireEvent.change(await screen.findByTestId("pay-periods-create-end"), {
        target: { value: "2026-02-28" },
      });
      fireEvent.change(await screen.findByTestId("pay-periods-create-pay-date"), {
        target: { value: "2026-03-05" },
      });
      fireEvent.change(await screen.findByTestId("pay-periods-create-cutoff"), {
        target: { value: "2026-02-28T23:59" },
      });
      fireEvent.click(await screen.findByTestId("pay-periods-create-submit"));

      await waitFor(() => {
        const post = calls.find(
          (c) =>
            c.method === "POST" && c.url.endsWith("/payroll/pay-periods"),
        );
        expect(post).toBeTruthy();
        const parsed = JSON.parse(post!.body) as { period_key: string };
        expect(parsed.period_key).toBe("2026-02");
      });
    },
    MODAL_TEST_TIMEOUT_MS,
  );
});
