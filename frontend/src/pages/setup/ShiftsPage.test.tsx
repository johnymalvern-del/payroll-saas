import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { ShiftsPage } from "./ShiftsPage";
function jr(b: unknown, s = 200): Response { return new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } }); }
function renderPage() { const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } }); return render(<QueryClientProvider client={qc}><MantineProvider><ShiftsPage /></MantineProvider></QueryClientProvider>); }
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe("ShiftsPage", () => {
  it("lists shifts", async () => {
    global.fetch = vi.fn(async () => jr({ items: [{ id: "sh1", name: "Day", start_time: "08:00", length_minutes: 480, unpaid_break_minutes: 0, paid_break_minutes: 0, grace_late_minutes: 0, grace_early_minutes: 0, rounding_minutes: 0, rounding_mode: "nearest", min_overtime_minutes: 0, overtime_requires_approval: false, max_shift_minutes: 720, match_tolerance_minutes: 0, salaried_premium_mode: "none", grace_mode: "none", pay_early_arrival: false, is_active: true, row_version: 1 }], next_cursor: null }));
    renderPage();
    await waitFor(() => expect(screen.getByText("Day")).toBeInTheDocument());
  });
});
