import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { WorkPatternsPage } from "./WorkPatternsPage";
function jr(b: unknown, s = 200): Response { return new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } }); }
function renderPage() { const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } }); return render(<QueryClientProvider client={qc}><MantineProvider><WorkPatternsPage /></MantineProvider></QueryClientProvider>); }
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe("WorkPatternsPage", () => {
  it("lists work patterns", async () => {
    global.fetch = vi.fn(async () => jr({ items: [{ id: "w1", name: "Standard 5-day", cycle_length_days: 7, anchor_date: "2024-01-01", is_active: true, row_version: 1 }], next_cursor: null }));
    renderPage();
    await waitFor(() => expect(screen.getByText("Standard 5-day")).toBeInTheDocument());
  });
});
