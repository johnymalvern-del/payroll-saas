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
import { ChangeRequestsPage } from "./ChangeRequestsPage";

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

type Call = { url: string; method: string; body: string };

const EMP = {
  id: "e1",
  employee_code: "EMP-001",
  first_name: "Ada",
  last_name: "Mokoena",
};

const REQ = {
  id: "cr1",
  kind: "employee_earning_create",
  employee_id: "e1",
  status: "pending",
  requested_by_user_id: "u1",
  requested_at: "2026-01-15T10:00:00Z",
  decided_by_user_id: null,
  decided_at: null,
  decision_note: null,
  applied_entity_id: null,
  assignment_id: null,
  row_version: 1,
};

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <ChangeRequestsPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ChangeRequestsPage", () => {
  it("renders pending request with employee name and action buttons", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      if (url.includes("/payroll/change-requests")) {
        return jr({ items: [REQ], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    const row = await screen.findByTestId("change-request-cr1");
    expect(within(row).getByText(/employee earning create/i)).toBeInTheDocument();
    expect(within(row).getByText(/Ada Mokoena/)).toBeInTheDocument();
    expect(within(row).getByText(/EMP-001/)).toBeInTheDocument();
    expect(within(row).getByTestId("change-request-approve-cr1")).toBeInTheDocument();
    expect(within(row).getByTestId("change-request-reject-cr1")).toBeInTheDocument();
    expect(within(row).getByTestId("change-request-cancel-cr1")).toBeInTheDocument();
  });

  it("shows empty text when no requests", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      if (url.includes("/payroll/change-requests")) {
        return jr({ items: [], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText(/no change requests match the current filters/i),
      ).toBeInTheDocument();
    });
  });

  it("shows load error with retry", async () => {
    let calls = 0;
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      if (url.includes("/payroll/change-requests")) {
        calls += 1;
        if (calls === 1) return jr({ error: { code: "boom" } }, 500);
        return jr({ items: [REQ], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await screen.findByTestId("change-requests-load-error");
    fireEvent.click(screen.getByTestId("change-requests-retry"));
    await screen.findByTestId("change-request-cr1");
  });

  it("status filter refetches with status query param", async () => {
    const calls: Call[] = [];
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      const method = requestMethod(input);
      calls.push({ url, method, body: "" });
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      if (url.includes("/payroll/change-requests")) {
        return jr({ items: [REQ], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await screen.findByTestId("change-request-cr1");

    const initial = calls.filter((c) =>
      c.url.includes("/payroll/change-requests"),
    );
    expect(initial[initial.length - 1].url).toContain("status=pending");

    fireEvent.click(screen.getByText("Approved"));
    await waitFor(() => {
      const updated = calls.filter((c) =>
        c.url.includes("/payroll/change-requests"),
      );
      expect(updated[updated.length - 1].url).toContain("status=approved");
    });
  });

  it(
    "approve modal posts to approve endpoint",
    async () => {
      const calls: Call[] = [];
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        const method = requestMethod(input);
        calls.push({ url, method, body: "" });
        if (method === "POST" && url.includes("/approve")) {
          return jr({ ...REQ, status: "approved" });
        }
        if (url.includes("/api/v1/employees")) {
          return jr({ items: [EMP], next_cursor: null });
        }
        if (url.includes("/payroll/change-requests")) {
          return jr({ items: [REQ], next_cursor: null });
        }
        return jr({}, 200);
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByTestId("change-request-cr1");
      fireEvent.click(screen.getByTestId("change-request-approve-cr1"));
      await screen.findByTestId("change-requests-modal");
      fireEvent.click(await screen.findByTestId("change-requests-modal-apply"));

      await waitFor(() => {
        const post = calls.find(
          (c) => c.method === "POST" && c.url.includes("/approve"),
        );
        expect(post).toBeTruthy();
      });
    },
    MODAL_TEST_TIMEOUT_MS,
  );

  it(
    "reject modal requires note before confirming",
    async () => {
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        if (url.includes("/api/v1/employees")) {
          return jr({ items: [EMP], next_cursor: null });
        }
        if (url.includes("/payroll/change-requests")) {
          return jr({ items: [REQ], next_cursor: null });
        }
        return jr({}, 200);
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByTestId("change-request-cr1");
      fireEvent.click(screen.getByTestId("change-request-reject-cr1"));
      await screen.findByTestId("change-requests-modal");

      const applyBtn = (await screen.findByTestId("change-requests-modal-apply")) as HTMLButtonElement;
      expect(applyBtn.disabled).toBe(true);

      fireEvent.change(await screen.findByTestId("change-requests-reject-note"), {
        target: { value: "not needed" },
      });
      await waitFor(() => {
        expect(
          (screen.getByTestId("change-requests-modal-apply") as HTMLButtonElement)
            .disabled,
        ).toBe(false);
      });
    },
    MODAL_TEST_TIMEOUT_MS,
  );

  it(
    "reject modal posts with note",
    async () => {
      const calls: Call[] = [];
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        const method = requestMethod(input);
        let body = "";
        if (method !== "GET" && input instanceof Request) {
          body = await input.clone().text();
        }
        calls.push({ url, method, body });
        if (method === "POST" && url.includes("/reject")) {
          return jr({ ...REQ, status: "rejected", decision_note: "not needed" });
        }
        if (url.includes("/api/v1/employees")) {
          return jr({ items: [EMP], next_cursor: null });
        }
        if (url.includes("/payroll/change-requests")) {
          return jr({ items: [REQ], next_cursor: null });
        }
        return jr({}, 200);
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByTestId("change-request-cr1");
      fireEvent.click(screen.getByTestId("change-request-reject-cr1"));
      await screen.findByTestId("change-requests-modal");
      fireEvent.change(await screen.findByTestId("change-requests-reject-note"), {
        target: { value: "not needed" },
      });
      fireEvent.click(await screen.findByTestId("change-requests-modal-apply"));

      await waitFor(() => {
        const post = calls.find(
          (c) => c.method === "POST" && c.url.includes("/reject"),
        );
        expect(post).toBeTruthy();
        const parsed = JSON.parse(post!.body) as { note: string };
        expect(parsed.note).toBe("not needed");
      });
    },
    MODAL_TEST_TIMEOUT_MS,
  );

  it(
    "cancel modal posts to cancel endpoint",
    async () => {
      const calls: Call[] = [];
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        const method = requestMethod(input);
        calls.push({ url, method, body: "" });
        if (method === "POST" && url.includes("/cancel")) {
          return jr({ ...REQ, status: "cancelled" });
        }
        if (url.includes("/api/v1/employees")) {
          return jr({ items: [EMP], next_cursor: null });
        }
        if (url.includes("/payroll/change-requests")) {
          return jr({ items: [REQ], next_cursor: null });
        }
        return jr({}, 200);
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByTestId("change-request-cr1");
      fireEvent.click(screen.getByTestId("change-request-cancel-cr1"));
      await screen.findByTestId("change-requests-modal");
      fireEvent.click(await screen.findByTestId("change-requests-modal-apply"));

      await waitFor(() => {
        const post = calls.find(
          (c) => c.method === "POST" && c.url.includes("/cancel"),
        );
        expect(post).toBeTruthy();
      });
    },
    MODAL_TEST_TIMEOUT_MS,
  );

  it("load more follows cursor", async () => {
    const calls: Call[] = [];
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      calls.push({ url, method: "GET", body: "" });
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      if (url.includes("/payroll/change-requests")) {
        if (url.includes("cursor=abc")) {
          return jr({ items: [], next_cursor: null });
        }
        return jr({ items: [REQ], next_cursor: "abc" });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await screen.findByTestId("change-request-cr1");
    fireEvent.click(screen.getByTestId("change-requests-load-more"));
    await waitFor(() => {
      const withCursor = calls.filter((c) => c.url.includes("cursor=abc"));
      expect(withCursor.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ---- assignment-link filter (M3.5 item 4) ----

  it("filters assignment-linked change requests out of the queue", async () => {
    const REQ_CHILD = {
      ...REQ,
      id: "cr2",
      assignment_id: "a1",
    };
    const REQ_INDIV = {
      ...REQ,
      id: "cr3",
      assignment_id: null,
    };
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      if (url.includes("/payroll/change-requests")) {
        return jr({ items: [REQ_CHILD, REQ_INDIV], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    // The individual request renders.
    await screen.findByTestId("change-request-cr3");
    // The assignment-linked request does not.
    expect(screen.queryByTestId("change-request-cr2")).toBeNull();
    // And the individual row has its action buttons.
    expect(screen.getByTestId("change-request-approve-cr3")).toBeInTheDocument();
  });

  it("load-more preserves the filter across pages", async () => {
    const PAGE1_CHILD = { ...REQ, id: "cr10", assignment_id: "a1" };
    const PAGE1_INDIV = { ...REQ, id: "cr11", assignment_id: null };
    const PAGE2_CHILD = { ...REQ, id: "cr20", assignment_id: "a2" };
    const PAGE2_INDIV = { ...REQ, id: "cr21", assignment_id: null };
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.includes("/api/v1/employees")) {
        return jr({ items: [EMP], next_cursor: null });
      }
      if (url.includes("/payroll/change-requests")) {
        if (url.includes("cursor=page2")) {
          return jr({ items: [PAGE2_CHILD, PAGE2_INDIV], next_cursor: null });
        }
        return jr({
          items: [PAGE1_CHILD, PAGE1_INDIV],
          next_cursor: "page2",
        });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await screen.findByTestId("change-request-cr11");
    expect(screen.queryByTestId("change-request-cr10")).toBeNull();

    fireEvent.click(screen.getByTestId("change-requests-load-more"));
    await screen.findByTestId("change-request-cr21");

    // Both individuals visible; both children still hidden.
    expect(screen.getByTestId("change-request-cr11")).toBeInTheDocument();
    expect(screen.getByTestId("change-request-cr21")).toBeInTheDocument();
    expect(screen.queryByTestId("change-request-cr10")).toBeNull();
    expect(screen.queryByTestId("change-request-cr20")).toBeNull();
  });
});