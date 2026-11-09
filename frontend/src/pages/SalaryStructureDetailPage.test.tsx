import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor, within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { SalaryStructureDetailPage } from "./SalaryStructureDetailPage";

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
  structure?: unknown;
  structureStatus?: number;
  versions?: unknown[];
  editResponse?: unknown;
  editStatus?: number;
  deactivateResponse?: unknown;
  deactivateStatus?: number;
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

    if (method === "POST" && url.includes("/deactivate")) {
      return jr(
        opts.deactivateResponse ??
          { deactivated: true, structure_group_id: "g1" },
        opts.deactivateStatus ?? 200,
      );
    }
    if (method === "PATCH" && url.includes("/salary-structures/g1")) {
      return jr(
        opts.editResponse ?? {
          id: "s2",
          structure_group_id: "g1",
          version_number: 2,
          is_current: true,
          name: "Edited",
          description: null,
          pay_basis: "monthly",
          base_rate: "20000",
          is_active: true,
          row_version: 1,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          components: [],
        },
        opts.editStatus ?? 200,
      );
    }
    if (url.includes("/salary-structures/g1/versions")) {
      return jr({ items: opts.versions ?? [] });
    }
    if (url.includes("/salary-structures/g1")) {
      return jr(
        opts.structure ?? {
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
          components: [
            {
              id: "c1", kind: "earning",
              earning_type_id: "et1", deduction_type_id: null,
              amount: "500", rate: null,
            },
          ],
        },
        opts.structureStatus ?? 200,
      );
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
        <MemoryRouter initialEntries={["/payroll/salary-structures/g1"]}>
          <Routes>
            <Route
              path="/payroll/salary-structures/:groupId"
              element={<SalaryStructureDetailPage />}
            />
            <Route
              path="/payroll/salary-structures"
              element={<div data-testid="back-target">Back</div>}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

const V1 = {
  id: "s1", structure_group_id: "g1", version_number: 1,
  is_current: true, name: "Monthly Basic", description: null,
  pay_basis: "monthly", base_rate: "18000", is_active: true,
  row_version: 1,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  components: [],
};
const V2 = { ...V1, id: "s2", version_number: 2, is_current: false };

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("SalaryStructureDetailPage", () => {
  it("renders structure name and version", async () => {
    setupMock({ versions: [V1] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structure-name")).toHaveTextContent("Monthly Basic"),
    );
    expect(screen.getByTestId("version-badge")).toHaveTextContent("Version 1");
  });

  it("renders components table", async () => {
    setupMock({ versions: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("components-table")).toBeInTheDocument(),
    );
    const row = screen.getByTestId("component-c1");
    expect(within(row).getByText("earning")).toBeInTheDocument();
    expect(within(row).getByText("500")).toBeInTheDocument();
  });

  it("shows error when structure fails to load", async () => {
    setupMock({ structureStatus: 500 });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("structure-error")).toBeInTheDocument(),
    );
  });

  it("renders version history table", async () => {
    setupMock({ versions: [V2, V1] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("versions-table")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("version-row-1")).toBeInTheDocument();
    expect(screen.getByTestId("version-row-2")).toBeInTheDocument();
  });

  it("opens edit modal on Edit click", async () => {
    setupMock({ versions: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("edit-button")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("edit-button"));
    const input = await screen.findByTestId("edit-name");
    expect((input as HTMLInputElement).value).toBe("Monthly Basic");
    const baseRate = screen.getByTestId("edit-base-rate") as HTMLInputElement;
    expect(baseRate.value).toBe("18000");
  });

  it("submits edit with version_number and row_version", async () => {
    const { calls } = setupMock({ versions: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("edit-button")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("edit-button"));
    await screen.findByTestId("edit-name");
    fireEvent.change(screen.getByTestId("edit-base-rate"), {
      target: { value: "20000" },
    });
    fireEvent.click(screen.getByTestId("edit-submit"));
    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH");
      expect(patch).toBeDefined();
      const b = JSON.parse(patch!.body);
      expect(b.version_number).toBe(1);
      expect(b.row_version).toBe(1);
      expect(b.base_rate).toBe("20000");
    });
  });

  it("shows edit error on record_changed", async () => {
    setupMock({
      versions: [],
      editStatus: 409,
      editResponse: { error: { code: "record_changed" } },
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("edit-button")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("edit-button"));
    await screen.findByTestId("edit-name");
    fireEvent.click(screen.getByTestId("edit-submit"));
    await waitFor(() =>
      expect(screen.getByTestId("edit-error")).toBeInTheDocument(),
    );
  });

  it("deactivate calls endpoint on confirm", async () => {
    const { calls } = setupMock({ versions: [] });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("deactivate-button")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("deactivate-button"));
    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.url.includes("/deactivate"))).toBe(true);
    });
  });

  it("deactivate does nothing on cancel", async () => {
    const { calls } = setupMock({ versions: [] });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("deactivate-button")).toBeInTheDocument(),
    );
    const before = calls.filter((c) => c.method === "POST").length;
    fireEvent.click(screen.getByTestId("deactivate-button"));
    await new Promise((r) => setTimeout(r, 50));
    const after = calls.filter((c) => c.method === "POST").length;
    expect(after).toBe(before);
  });

  it("back link points to the structures list", async () => {
    setupMock({ versions: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("back-link")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("back-link")).toHaveAttribute(
      "href", "/payroll/salary-structures",
    );
  });
});