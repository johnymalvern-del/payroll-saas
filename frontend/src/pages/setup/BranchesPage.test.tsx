import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { BranchesPage } from "./BranchesPage";
function jr(b: unknown, s = 200): Response { return new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } }); }
function renderPage() { const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } }); return render(<QueryClientProvider client={qc}><MantineProvider><BranchesPage /></MantineProvider></QueryClientProvider>); }
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe("BranchesPage", () => {
  it("lists branches", async () => {
    global.fetch = vi.fn(async () => jr({ items: [{ id: "b1", name: "HQ", code: "HQ1", address: null, is_active: true, row_version: 1 }], next_cursor: null }));
    renderPage();
    await waitFor(() => expect(screen.getByText("HQ")).toBeInTheDocument());
  });
});
