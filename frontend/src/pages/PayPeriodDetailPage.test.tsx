import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import {
  MemoryRouter,
  Route,
  Routes,
} from "react-router-dom";
import { PayPeriodDetailPage } from "./PayPeriodDetailPage";

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

const PERIOD_OPEN = {
  id: "pp1",
  period_key: "2026-01",
  start_date: "2026-01-01",
  end_date: "2026-01-31",
  pay_date: "2026-02-05",
  status: "open",
  cutoff_at: "2026-01-31T23:59:00+00:00",
  row_version: 1,
};

const PERIOD_LOCKED = { ...PERIOD_OPEN, status: "locked" };

const PREVIEW = {
  run_id: "r1",
  revision: 1,
  status: "completed",
  unacknowledged_formulas: [],
  items: [
    {
      employee_id: "e1",
      employee_code: "E001",
      employee_name: "Ada",
      gross: "1000.00",
      paye: "100.00",
      net: "890.00",
      warnings: [],
    },
  ],
  next_cursor: null,
};

const RUN_OUT = {
  id: "run-final",
  pay_period_id: "pp1",
  kind: "final",
  revision: 1,
  status: "completed",
  started_at: "2026-02-05T00:00:00Z",
  completed_at: "2026-02-05T00:01:00Z",
  error_code: null,
};

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/payroll/pay-periods/pp1"]}>
          <Routes>
            <Route
              path="/payroll/pay-periods/:id"
              element={<PayPeriodDetailPage />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PayPeriodDetailPage", () => {
  it("renders period and preview button", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.endsWith("/payroll/pay-periods/pp1")) {
        return jr(PERIOD_OPEN);
      }
      return jr({});
    }) as unknown as typeof fetch;

    renderPage();
    expect(
      await screen.findByText(/Pay period 2026-01/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("pay-period-preview")).toBeInTheDocument();
  });

  it("preview button shows employee rows", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      const method = requestMethod(input);
      if (url.endsWith("/payroll/pay-periods/pp1") && method === "GET") {
        return jr(PERIOD_OPEN);
      }
      if (url.includes("/preview") && method === "POST") {
        return jr(PREVIEW);
      }
      return jr({});
    }) as unknown as typeof fetch;

    renderPage();
    await screen.findByText(/Pay period 2026-01/);
    fireEvent.click(screen.getByTestId("pay-period-preview"));
    const result = await screen.findByTestId("pay-period-preview-result");
    expect(result.textContent ?? "").toMatch(/Ada/);
  });

  it("preview shows out-of-scope banner when caller's scope is empty", async () => {
    const PREVIEW_OUT_OF_SCOPE = {
      ...PREVIEW,
      items: [],
      raw_employee_count: 2,
    };
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      const method = requestMethod(input);
      if (url.endsWith("/payroll/pay-periods/pp1") && method === "GET") {
        return jr(PERIOD_OPEN);
      }
      if (url.includes("/preview") && method === "POST") {
        return jr(PREVIEW_OUT_OF_SCOPE);
      }
      return jr({});
    }) as unknown as typeof fetch;

    renderPage();
    await screen.findByText(/Pay period 2026-01/);
    fireEvent.click(screen.getByTestId("pay-period-preview"));
    const banner = await screen.findByTestId(
      "pay-period-preview-out-of-scope",
    );
    expect(banner.textContent ?? "").toMatch(/access scope/i);
  }, MODAL_TEST_TIMEOUT_MS);

  it(
    "finalise shows ack field after open_exceptions_in_period error",
    async () => {
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        const method = requestMethod(input);
        if (url.endsWith("/payroll/pay-periods/pp1") && method === "GET") {
          return jr(PERIOD_OPEN);
        }
        if (url.endsWith("/finalise") && method === "POST") {
          return jr(
            {
              error: {
                code: "open_exceptions_in_period",
                details: { count: 2, sample: [] },
              },
            },
            409,
          );
        }
        return jr({});
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByText(/Pay period 2026-01/);
      fireEvent.click(screen.getByTestId("pay-period-finalise-open"));
      await screen.findByTestId("pay-period-finalise-modal");
      fireEvent.click(await screen.findByTestId("pay-period-finalise-submit"));

      await waitFor(() => {
        expect(
          screen.getByTestId("pay-period-finalise-error").textContent ?? "",
        ).toMatch(/open exceptions/i);
      });
      expect(
        screen.getByTestId("pay-period-finalise-ack"),
      ).toBeInTheDocument();
    },
    MODAL_TEST_TIMEOUT_MS,
  );

  it(
    "reopen requires reason",
    async () => {
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        const method = requestMethod(input);
        if (url.endsWith("/payroll/pay-periods/pp1") && method === "GET") {
          return jr(PERIOD_LOCKED);
        }
        return jr([]);
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByText(/Pay period 2026-01/);
      fireEvent.click(screen.getByTestId("pay-period-reopen-open"));
      await screen.findByTestId("pay-period-reopen-modal");
      fireEvent.click(await screen.findByTestId("pay-period-reopen-submit"));

      await waitFor(() => {
        expect(
          screen.getByTestId("pay-period-reopen-error").textContent ?? "",
        ).toMatch(/reason is required/i);
      });
    },
    MODAL_TEST_TIMEOUT_MS,
  );

  // ---- Stage 6 — pending-CR and stale-preview states ----

  it(
    "finalise shows pending-CR guidance and disables submit when backend blocks",
    async () => {
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        const method = requestMethod(input);
        if (url.endsWith("/payroll/pay-periods/pp1") && method === "GET") {
          return jr(PERIOD_OPEN);
        }
        if (url.endsWith("/finalise") && method === "POST") {
          return jr(
            {
              error: {
                code: "pending_change_requests_in_period",
                details: { count: 3, sample: [] },
              },
            },
            409,
          );
        }
        return jr({});
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByText(/Pay period 2026-01/);
      fireEvent.click(screen.getByTestId("pay-period-finalise-open"));
      await screen.findByTestId("pay-period-finalise-modal");
      fireEvent.click(await screen.findByTestId("pay-period-finalise-submit"));

      await waitFor(() => {
        expect(
          screen.getByTestId("pay-period-finalise-error").textContent ?? "",
        ).toMatch(/3 pending change request/i);
      });

      expect(
        screen.getByTestId("pay-period-finalise-pending-cr-guidance"),
      ).toBeInTheDocument();

      expect(
        (screen.getByTestId("pay-period-finalise-submit") as HTMLButtonElement)
          .disabled,
      ).toBe(true);

      expect(screen.queryByTestId("pay-period-finalise-stale-ack")).toBeNull();
    },
    MODAL_TEST_TIMEOUT_MS,
  );

  it(
    "finalise shows stale-preview warning and ack field when backend blocks",
    async () => {
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        const method = requestMethod(input);
        if (url.endsWith("/payroll/pay-periods/pp1") && method === "GET") {
          return jr(PERIOD_OPEN);
        }
        if (url.endsWith("/finalise") && method === "POST") {
          return jr(
            {
              error: {
                code: "preview_stale",
                details: {
                  preview_hash: "aaaa",
                  current_hash: "bbbb",
                },
              },
            },
            409,
          );
        }
        return jr({});
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByText(/Pay period 2026-01/);
      fireEvent.click(screen.getByTestId("pay-period-finalise-open"));
      await screen.findByTestId("pay-period-finalise-modal");
      fireEvent.click(await screen.findByTestId("pay-period-finalise-submit"));

      await screen.findByTestId("pay-period-finalise-stale-warning");

      expect(
        screen.getByTestId("pay-period-finalise-stale-ack"),
      ).toBeInTheDocument();

      expect(
        screen.getByTestId("pay-period-finalise-rerun-preview"),
      ).toBeInTheDocument();

      fireEvent.click(screen.getByTestId("pay-period-finalise-submit"));
      await waitFor(() => {
        expect(
          screen.getByTestId("pay-period-finalise-error").textContent ?? "",
        ).toMatch(/reason to acknowledge the stale preview/i);
      });
    },
    MODAL_TEST_TIMEOUT_MS,
  );

  it(
    "finalise resubmits with ack_stale_preview_reason after stale error",
    async () => {
      let finaliseCallCount = 0;
      const capturedBodies: string[] = [];
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        const method = requestMethod(input);
        if (url.endsWith("/payroll/pay-periods/pp1") && method === "GET") {
          return jr(PERIOD_OPEN);
        }
        if (url.endsWith("/finalise") && method === "POST") {
          finaliseCallCount++;
          // Capture only when a body is present. First finalise is body-less
          // (no ack reasons); second carries ack_stale_preview_reason.
          if (input instanceof Request && input.body) {
            capturedBodies.push(await input.text());
          }
          if (finaliseCallCount === 1) {
            return jr(
              {
                error: {
                  code: "preview_stale",
                  details: {
                    preview_hash: "aaaa",
                    current_hash: "bbbb",
                  },
                },
              },
              409,
            );
          }
          return jr(RUN_OUT);
        }
        return jr({});
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByText(/Pay period 2026-01/);
      fireEvent.click(screen.getByTestId("pay-period-finalise-open"));
      await screen.findByTestId("pay-period-finalise-modal");
      fireEvent.click(await screen.findByTestId("pay-period-finalise-submit"));
      await screen.findByTestId("pay-period-finalise-stale-warning");

      fireEvent.change(screen.getByTestId("pay-period-finalise-stale-ack"), {
        target: { value: "cfo approved post-preview correction" },
      });
      fireEvent.click(screen.getByTestId("pay-period-finalise-submit"));

      await waitFor(() => {
        expect(finaliseCallCount).toBe(2);
      });

      // Only the SECOND call had a body. If the first call had also carried
      // a body, this count would be 2 and we would index [1]; but proving
      // "first call body-less" is a stronger invariant, so assert exactly 1.
      expect(capturedBodies.length).toBe(1);
      expect(capturedBodies[0]).toMatch(/ack_stale_preview_reason/);
      expect(capturedBodies[0]).toMatch(/cfo approved post-preview correction/);

      // Success clears the stale-ack state synchronously.
      await waitFor(() => {
        expect(
          screen.queryByTestId("pay-period-finalise-stale-warning"),
        ).toBeNull();
      });
    },
    MODAL_TEST_TIMEOUT_MS,
  );

  it(
    "re-run preview button closes modal and triggers preview",
    async () => {
      let previewCallCount = 0;
      let finaliseCallCount = 0;
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        const method = requestMethod(input);
        if (url.endsWith("/payroll/pay-periods/pp1") && method === "GET") {
          return jr(PERIOD_OPEN);
        }
        if (url.includes("/preview") && method === "POST") {
          previewCallCount++;
          return jr(PREVIEW);
        }
        if (url.endsWith("/finalise") && method === "POST") {
          finaliseCallCount++;
          return jr(
            {
              error: {
                code: "preview_stale",
                details: { preview_hash: "a", current_hash: "b" },
              },
            },
            409,
          );
        }
        return jr({});
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByText(/Pay period 2026-01/);
      fireEvent.click(screen.getByTestId("pay-period-finalise-open"));
      await screen.findByTestId("pay-period-finalise-modal");
      fireEvent.click(await screen.findByTestId("pay-period-finalise-submit"));
      await screen.findByTestId("pay-period-finalise-stale-warning");

      fireEvent.click(screen.getByTestId("pay-period-finalise-rerun-preview"));

      await waitFor(() => {
        expect(
          screen.queryByTestId("pay-period-finalise-stale-warning"),
        ).toBeNull();
      });

      await waitFor(() => {
        expect(previewCallCount).toBe(1);
      });

      expect(finaliseCallCount).toBe(1);

      await screen.findByTestId("pay-period-preview-result");
    },
    MODAL_TEST_TIMEOUT_MS,
  );
});