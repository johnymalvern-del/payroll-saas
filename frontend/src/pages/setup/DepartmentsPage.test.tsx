import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { DepartmentsPage } from "./DepartmentsPage";
function jr(b: unknown, s = 200): Response { return new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } }); }
function renderPage() { const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } }); return render(<QueryClientProvider client={qc}><MantineProvider><DepartmentsPage /></MantineProvider></QueryClientProvider>); }
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe("DepartmentsPage", () => {
  it("lists departments", async () => {
    global.fetch = vi.fn(async () => jr({ items: [{ id: "d1", name: "Ops", code: "OPS", parent_id: null, is_active: true, row_version: 1 }], next_cursor: null }));
    renderPage();
    await waitFor(() => expect(screen.getByText("Ops")).toBeInTheDocument());
  });
});
