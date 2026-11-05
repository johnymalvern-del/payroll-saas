import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { PublicHolidaysPage } from "./PublicHolidaysPage";
function jr(b: unknown, s = 200): Response { return new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } }); }
function renderPage() { const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } }); return render(<QueryClientProvider client={qc}><MantineProvider><PublicHolidaysPage /></MantineProvider></QueryClientProvider>); }
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe("PublicHolidaysPage", () => {
  it("lists holidays", async () => {
    global.fetch = vi.fn(async () => jr({ items: [{ id: "h1", holiday_date: "2026-12-25", name: "Xmas", site_id: null, department_id: null, is_working_day_override: false, is_active: true, row_version: 1 }], next_cursor: null }));
    renderPage();
    await waitFor(() => expect(screen.getByText("Xmas")).toBeInTheDocument());
  });
});
