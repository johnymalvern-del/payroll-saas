"""Bundle 1 test fix: mock useMe in ClockInPage.test; use findByTestId for
modal content in DevicesPage.test."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

FILES = {
    "src/pages/ClockInPage.test.tsx": '''import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { ClockInPage } from "./ClockInPage";

vi.mock("../lib/camera", () => ({
  startCamera: vi.fn(async () => ({
    stop: vi.fn(),
    captureJpegBase64: () => "fake-jpeg-base64",
  })),
}));

vi.mock("../auth/useMe", () => ({
  useMe: () => ({
    data: {
      id: "u1",
      username: "admin",
      role: "payroll_admin",
      employee_id: null,
      permissions: [],
      must_change_password: false,
      default_timezone: "Africa/Johannesburg",
    },
    isLoading: false,
    isError: false,
    error: null,
  }),
}));

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
        <ClockInPage />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* ignored */
  }
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ClockInPage", () => {
  it("asks for the device key when none is stored", () => {
    renderPage();
    expect(screen.getByTestId("clockin-device-key")).toBeInTheDocument();
  });

  it("saves the key and shows the clock-in form", () => {
    renderPage();
    fireEvent.change(screen.getByTestId("clockin-device-key"), {
      target: { value: "devkey123" },
    });
    fireEvent.click(screen.getByTestId("clockin-save-key"));
    expect(screen.getByTestId("clockin-code")).toBeInTheDocument();
    expect(localStorage.getItem("payroll.device_key")).toBe("devkey123");
  });

  it("reset device clears the key and returns to prompt", () => {
    renderPage();
    fireEvent.change(screen.getByTestId("clockin-device-key"), {
      target: { value: "k" },
    });
    fireEvent.click(screen.getByTestId("clockin-save-key"));
    fireEvent.click(screen.getByTestId("clockin-reset-device"));
    expect(screen.getByTestId("clockin-device-key")).toBeInTheDocument();
    expect(localStorage.getItem("payroll.device_key")).toBeNull();
  });

  it("looks up employee by code and shows name", async () => {
    global.fetch = vi.fn(async () =>
      jr({
        items: [
          {
            id: "00000000-0000-0000-0000-000000000001",
            employee_code: "E1",
            first_name: "Ada",
            last_name: "Lovelace",
          },
        ],
      }),
    );
    renderPage();
    fireEvent.change(screen.getByTestId("clockin-device-key"), {
      target: { value: "k" },
    });
    fireEvent.click(screen.getByTestId("clockin-save-key"));
    fireEvent.change(screen.getByTestId("clockin-code"), {
      target: { value: "E1" },
    });
    fireEvent.click(screen.getByTestId("clockin-lookup"));
    await waitFor(() =>
      expect(screen.getByTestId("clockin-emp")).toHaveTextContent(/Ada/),
    );
  });

  it("shows error when code matches nothing", async () => {
    global.fetch = vi.fn(async () => jr({ items: [] }));
    renderPage();
    fireEvent.change(screen.getByTestId("clockin-device-key"), {
      target: { value: "k" },
    });
    fireEvent.click(screen.getByTestId("clockin-save-key"));
    fireEvent.change(screen.getByTestId("clockin-code"), {
      target: { value: "ZZZ" },
    });
    fireEvent.click(screen.getByTestId("clockin-lookup"));
    await waitFor(() =>
      expect(screen.getByTestId("clockin-error")).toBeInTheDocument(),
    );
  });
});
''',

    "src/pages/setup/DevicesPage.test.tsx": '''import { afterEach, describe, expect, it, vi } from "vitest";
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
''',
}

for rel, content in FILES.items():
    p = FRONTEND / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"wrote {rel} ({len(content)} bytes)")