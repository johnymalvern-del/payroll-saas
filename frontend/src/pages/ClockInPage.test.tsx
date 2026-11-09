import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

  it("shows warning when punch succeeds but attendance recompute fails", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/employees?employee_code=")) {
        return jr({
          items: [
            {
              id: "e1",
              employee_code: "E1",
              first_name: "A",
              last_name: "B",
            },
          ],
        });
      }
      if (url.includes("/punches")) {
        return jr(
          {
            id: "p1",
            effective_time: "2026-11-10T08:00:00Z",
            status: "accepted",
            flags: [],
            warnings: ["attendance_recompute_failed"],
          },
          201,
        );
      }
      return jr({});
    });
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
      expect(screen.getByTestId("clockin-emp")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("clockin-start-camera"));
    await waitFor(() =>
      expect(screen.getByTestId("clockin-stop-camera")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("clockin-submit"));
    await waitFor(() =>
      expect(
        screen.getByTestId("clockin-recompute-warning"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/punch was recorded, but attendance/i))
      .toBeInTheDocument();
    expect(screen.queryByTestId("clockin-success")).not.toBeInTheDocument();
  });

});
