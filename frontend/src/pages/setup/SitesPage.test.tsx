import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { SitesPage } from "./SitesPage";

function jr(b: unknown, s = 200): Response {
  return new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });
}
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MantineProvider><SitesPage /></MantineProvider></QueryClientProvider>);
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe("SitesPage", () => {
  it("lists sites", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/branches")) return jr({ items: [], next_cursor: null });
      return jr({ items: [{ id: "s1", branch_id: "b1", name: "Main", code: "M1", site_type: null, address: null, timezone: "Africa/Johannesburg", latitude: null, longitude: null, geofence_radius_m: null, is_active: true, row_version: 1 }], next_cursor: null });
    });
    renderPage();
    await waitFor(() => expect(screen.getByText("Main")).toBeInTheDocument());
  });
});
