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
import { DevicesPage } from "./DevicesPage";

function jr(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <DevicesPage />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("DevicesPage", () => {
  it("lists devices", async () => {
    global.fetch = vi.fn(async () =>
      jr({
        items: [
          {
            id: "d1",
            site_id: "s1",
            name: "Front gate",
            device_type: "kiosk",
            status: "active",
            last_seen_at: null,
            last_sync_at: null,
            pending_punch_count: 0,
            allows_code_only: false,
            require_photo_for_code: true,
            software_version: null,
            row_version: 1,
          },
        ],
        next_cursor: null,
      }),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Front gate")).toBeInTheDocument(),
    );
  });

  it("creates a device and shows the key once", async () => {
    global.fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (init?.method === "POST" && url.includes("/devices")) {
          return jr(
            {
              id: "new",
              site_id: "s1",
              name: "N",
              device_type: "kiosk",
              status: "active",
              pending_punch_count: 0,
              allows_code_only: false,
              require_photo_for_code: true,
              row_version: 1,
              api_key: "SECRET_KEY",
            },
            201,
          );
        }
        return jr({ items: [], next_cursor: null });
      },
    );
    renderPage();
    const addBtn = await screen.findByTestId("devices-add");
    fireEvent.click(addBtn);
    const siteInput = await screen.findByTestId("devices-site-id");
    fireEvent.change(siteInput, {
      target: { value: "11111111-1111-1111-1111-111111111111" },
    });
    const nameInput = await screen.findByTestId("devices-name");
    fireEvent.change(nameInput, { target: { value: "N" } });
    fireEvent.click(screen.getByTestId("devices-create"));
    await waitFor(() =>
      expect(screen.getByTestId("devices-created-key")).toHaveTextContent(
        /SECRET_KEY/,
      ),
    );
  });
});
