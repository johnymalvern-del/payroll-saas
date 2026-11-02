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
import { EmployeesPage } from "./EmployeesPage";

if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {};
}

// Modal-opening tests take longer under full-suite CPU pressure (6 ref
// queries + Mantine Modal transition + POST + invalidations). Vitest's
// default 5s per-test timeout is too tight when 8 files run in parallel;
// single-file runs land at ~2.5s/test, full-suite can hit 6-8s. Give
// modal tests their own budget; leave the list-only tests on the default.
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

const EMP1 = {
  id: "e1",
  employee_code: "EMP-001",
  first_name: "Ada",
  last_name: "Mokoena",
  national_id_masked: "***1234",
  email: "ada@example.com",
  mobile: "0721234567",
  date_of_birth: "1990-01-01",
  hire_date: "2024-01-15",
  termination_date: null,
  status: "active",
  job_title: "Developer",
  branch_id: null,
  site_id: null,
  department_id: null,
  manager_id: null,
  employee_type: "hourly",
  pay_basis: "hourly",
  pay_frequency: "monthly",
  base_rate: null,
  overtime_eligible: true,
  clocks: true,
  work_pattern_id: null,
  default_shift_id: null,
  bank_name: null,
  bank_account_number_masked: null,
  bank_branch_code: null,
  account_type: null,
  tax_number: null,
  medical_aid_dependants: 0,
  retirement_fund_flags: null,
  uif_exempt: false,
  notes: null,
  row_version: 1,
  site_timezone: "Africa/Johannesburg",
};

const EMP2 = {
  ...EMP1,
  id: "e2",
  employee_code: "EMP-002",
  first_name: "Sipho",
  last_name: "Dlamini",
  row_version: 2,
};

type Call = { url: string; method: string; body: string };

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <EmployeesPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

function refsHandlers(url: string): Response | null {
  if (url.includes("/branches")) return jr({ items: [], next_cursor: null });
  if (url.includes("/sites")) return jr({ items: [], next_cursor: null });
  if (url.includes("/departments"))
    return jr({ items: [], next_cursor: null });
  if (url.includes("/work-patterns"))
    return jr({ items: [], next_cursor: null });
  if (url.includes("/shifts")) return jr({ items: [], next_cursor: null });
  if (url.includes("/employees") && url.includes("limit=500"))
    return jr({ items: [], next_cursor: null });
  return null;
}

function isListQuery(url: string, method: string): boolean {
  if (method !== "GET") return false;
  if (!url.includes("/employees")) return false;
  if (url.includes("limit=500")) return false;
  return true;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("EmployeesPage", () => {
  beforeEach(() => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      const method = requestMethod(input);
      const refs = refsHandlers(url);
      if (refs) return refs;
      if (isListQuery(url, method)) {
        return jr({ items: [EMP1, EMP2], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;
  });

  it("renders the list with both employees", async () => {
    renderPage();
    await screen.findByTestId("employee-e1");
    expect(screen.getByTestId("employee-e2")).toBeInTheDocument();
    const row = screen.getByTestId("employee-e1");
    expect(within(row).getByText(/Ada Mokoena/)).toBeInTheDocument();
    expect(within(row).getByText(/EMP-001/)).toBeInTheDocument();
  });

  it("shows empty text when no employees", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      const method = requestMethod(input);
      const refs = refsHandlers(url);
      if (refs) return refs;
      if (isListQuery(url, method))
        return jr({ items: [], next_cursor: null });
      return jr({}, 200);
    }) as unknown as typeof fetch;
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText(/no employees match these filters/i),
      ).toBeInTheDocument();
    });
  });

  it("shows error state with retry", async () => {
    let listCalls = 0;
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      const method = requestMethod(input);
      const refs = refsHandlers(url);
      if (refs) return refs;
      if (isListQuery(url, method)) {
        listCalls += 1;
        if (listCalls === 1) return jr({ error: { code: "boom" } }, 500);
        return jr({ items: [EMP1], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;
    renderPage();
    await screen.findByTestId("employees-error", undefined, {
      timeout: 5000,
    });
    fireEvent.click(screen.getByTestId("employees-retry"));
    await screen.findByTestId("employee-e1", undefined, { timeout: 5000 });
  });

  it("Load more follows next_cursor and appends", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      const method = requestMethod(input);
      const refs = refsHandlers(url);
      if (refs) return refs;
      if (isListQuery(url, method)) {
        if (url.includes("cursor=abc")) {
          return jr({ items: [EMP2], next_cursor: null });
        }
        return jr({ items: [EMP1], next_cursor: "abc" });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;
    renderPage();
    await screen.findByTestId("employee-e1");
    expect(screen.queryByTestId("employee-e2")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("employees-load-more"));
    await screen.findByTestId("employee-e2");
  });

  it(
    "New button opens form; submit POSTs to /employees",
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
        const refs = refsHandlers(url);
        if (refs) return refs;
        if (method === "POST" && url.match(/\/api\/v1\/employees\/?$/)) {
          return jr(EMP1, 201);
        }
        if (isListQuery(url, method)) {
          return jr({ items: [EMP1], next_cursor: null });
        }
        return jr({}, 200);
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByTestId("employee-e1", undefined, { timeout: 5000 });
      fireEvent.click(screen.getByTestId("employees-new"));
      await screen.findByTestId("emp-code", undefined, { timeout: 10000 });
      fireEvent.change(screen.getByTestId("emp-code"), {
        target: { value: "EMP-099" },
      });
      fireEvent.change(screen.getByTestId("emp-first-name"), {
        target: { value: "New" },
      });
      fireEvent.change(screen.getByTestId("emp-last-name"), {
        target: { value: "Person" },
      });
      fireEvent.change(screen.getByTestId("emp-hire-date"), {
        target: { value: "2025-01-01" },
      });
      fireEvent.click(screen.getByTestId("emp-submit"));

      await waitFor(
        () => {
          const post = calls.find(
            (c) =>
              c.method === "POST" && c.url.match(/\/api\/v1\/employees\/?$/),
          );
          expect(post).toBeTruthy();
          const parsed = JSON.parse(post!.body) as { employee_code: string };
          expect(parsed.employee_code).toBe("EMP-099");
        },
        { timeout: 10000 },
      );
    },
    MODAL_TEST_TIMEOUT_MS,
  );

  it("Edit opens form with row data prefilled", async () => {
    renderPage();
    await screen.findByTestId("employee-e1");
    fireEvent.click(screen.getByTestId("employee-edit-e1"));
    const dialog = await screen.findByRole("dialog", undefined, {
      timeout: 10000,
    });
    const codeInput = within(dialog).getByTestId(
      "emp-code",
    ) as HTMLInputElement;
    await waitFor(() => expect(codeInput.value).toBe("EMP-001"), {
      timeout: 5000,
    });
    const firstName = within(dialog).getByTestId(
      "emp-first-name",
    ) as HTMLInputElement;
    expect(firstName.value).toBe("Ada");
  });

  it(
    "Edit PATCHes with row_version",
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
        const refs = refsHandlers(url);
        if (refs) return refs;
        if (method === "PATCH" && url.includes("/api/v1/employees/e1")) {
          return jr({ ...EMP1, job_title: "Senior" });
        }
        if (isListQuery(url, method)) {
          return jr({ items: [EMP1], next_cursor: null });
        }
        return jr({}, 200);
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByTestId("employee-e1");
      fireEvent.click(screen.getByTestId("employee-edit-e1"));
      await screen.findByTestId("emp-job-title", undefined, {
        timeout: 10000,
      });
      fireEvent.change(screen.getByTestId("emp-job-title"), {
        target: { value: "Senior" },
      });
      fireEvent.click(screen.getByTestId("emp-submit"));
      await waitFor(
        () => {
          const patch = calls.find(
            (c) =>
              c.method === "PATCH" && c.url.includes("/api/v1/employees/e1"),
          );
          expect(patch).toBeTruthy();
          const parsed = JSON.parse(patch!.body) as {
            row_version: number;
            job_title: string;
          };
          expect(parsed.row_version).toBe(1);
          expect(parsed.job_title).toBe("Senior");
        },
        { timeout: 10000 },
      );
    },
    MODAL_TEST_TIMEOUT_MS,
  );

  it("Terminate confirms and PATCHes status=terminated", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const calls: Call[] = [];
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      const method = requestMethod(input);
      let body = "";
      if (method !== "GET" && input instanceof Request) {
        body = await input.clone().text();
      }
      calls.push({ url, method, body });
      const refs = refsHandlers(url);
      if (refs) return refs;
      if (method === "PATCH" && url.includes("/api/v1/employees/e1")) {
        return jr({ ...EMP1, status: "terminated", row_version: 2 });
      }
      if (isListQuery(url, method)) {
        return jr({ items: [EMP1], next_cursor: null });
      }
      return jr({}, 200);
    }) as unknown as typeof fetch;

    renderPage();
    await screen.findByTestId("employee-e1");
    fireEvent.click(screen.getByTestId("employee-terminate-e1"));
    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    await waitFor(
      () => {
        const patch = calls.find(
          (c) =>
            c.method === "PATCH" && c.url.includes("/api/v1/employees/e1"),
        );
        expect(patch).toBeTruthy();
        const parsed = JSON.parse(patch!.body) as { status: string };
        expect(parsed.status).toBe("terminated");
      },
      { timeout: 5000 },
    );
  });

  it("Validation: empty first name blocks submit", async () => {
    renderPage();
    await screen.findByTestId("employee-e1");
    fireEvent.click(screen.getByTestId("employees-new"));
    const dialog = await screen.findByRole("dialog", undefined, {
      timeout: 10000,
    });
    fireEvent.change(within(dialog).getByTestId("emp-code"), {
      target: { value: "EMP-X" },
    });
    fireEvent.click(within(dialog).getByTestId("emp-submit"));
    await waitFor(
      () => {
        expect(
          within(dialog).getByText(/first name is required/i),
        ).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
  });

  it(
    "duplicate_code error is mapped on create",
    async () => {
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        const method = requestMethod(input);
        const refs = refsHandlers(url);
        if (refs) return refs;
        if (method === "POST" && url.match(/\/api\/v1\/employees\/?$/)) {
          return jr({ error: { code: "duplicate_code" } }, 409);
        }
        if (isListQuery(url, method)) {
          return jr({ items: [EMP1], next_cursor: null });
        }
        return jr({}, 200);
      }) as unknown as typeof fetch;

      renderPage();
      await screen.findByTestId("employee-e1");
      fireEvent.click(screen.getByTestId("employees-new"));
      const dialog = await screen.findByRole("dialog", undefined, {
        timeout: 10000,
      });
      fireEvent.change(within(dialog).getByTestId("emp-code"), {
        target: { value: "EMP-001" },
      });
      fireEvent.change(within(dialog).getByTestId("emp-first-name"), {
        target: { value: "Dup" },
      });
      fireEvent.change(within(dialog).getByTestId("emp-last-name"), {
        target: { value: "Person" },
      });
      fireEvent.change(within(dialog).getByTestId("emp-hire-date"), {
        target: { value: "2025-01-01" },
      });
      fireEvent.click(within(dialog).getByTestId("emp-submit"));
      await waitFor(
        () => {
          expect(
            within(dialog).getByTestId("employee-form-error").textContent ?? "",
          ).toMatch(/code already exists/i);
        },
        { timeout: 10000 },
      );
    },
    MODAL_TEST_TIMEOUT_MS,
  );
});