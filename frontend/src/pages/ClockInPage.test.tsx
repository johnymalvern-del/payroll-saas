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

function stubGeo(
  outcome:
    | { kind: "ok"; accuracy: number; lat?: number; lon?: number }
    | { kind: "denied" }
    | { kind: "timeout" },
): void {
  const value = {
    getCurrentPosition: (
      success: PositionCallback,
      error?: PositionErrorCallback | null,
    ) => {
      if (outcome.kind === "ok") {
        success({
          coords: {
            latitude: outcome.lat ?? -33.9249,
            longitude: outcome.lon ?? 18.4241,
            accuracy: outcome.accuracy,
          },
        } as GeolocationPosition);
        return;
      }
      const code = outcome.kind === "denied" ? 1 : 3;
      error?.({
        code,
        PERMISSION_DENIED: 1,
        POSITION_UNAVAILABLE: 2,
        TIMEOUT: 3,
        message: outcome.kind,
      } as unknown as GeolocationPositionError);
    },
  };
  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    writable: true,
    value,
  });
}

function stubNoGeo(): void {
  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    writable: true,
    value: undefined,
  });
}

const EMP = {
  id: "00000000-0000-0000-0000-000000000001",
  employee_code: "E1",
  first_name: "Ada",
  last_name: "Lovelace",
};

function stubFetch(punch: unknown, sent: { body?: Record<string, unknown> } = {}) {
  global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/employees?employee_code=")) {
      return jr({ items: [EMP] });
    }
    if (url.includes("/punches")) {
      if (init?.body) sent.body = JSON.parse(String(init.body));
      return jr(punch, 201);
    }
    return jr({});
  });
}

/**
 * fetch stub for the PIN path: employee lookup succeeds, and the punch POST
 * returns whatever status/body the test supplies.
 */
function stubFetchPunchError(
  status: number,
  code: string,
  message: string,
  sent: { body?: Record<string, unknown> } = {},
) {
  global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/employees?employee_code=")) {
      return jr({ items: [EMP] });
    }
    if (url.includes("/punches")) {
      if (init?.body) sent.body = JSON.parse(String(init.body));
      return jr({ error: { code, message } }, status);
    }
    return jr({});
  });
}

const BASE_PUNCH = {
  id: "p1",
  effective_time: "2026-11-10T08:00:00Z",
  status: "accepted",
  flags: [],
  warnings: [],
};

async function lookupOnly() {
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
}

async function clockInFlow() {
  await lookupOnly();
  fireEvent.click(screen.getByTestId("clockin-start-camera"));
  await waitFor(() =>
    expect(screen.getByTestId("clockin-stop-camera")).toBeInTheDocument(),
  );
  fireEvent.click(screen.getByTestId("clockin-submit"));
}

async function pinFlow(pin = "481920") {
  await lookupOnly();
  fireEvent.click(screen.getByText("Use a PIN instead"));
  await waitFor(() =>
    expect(screen.getByTestId("clockin-pin")).toBeInTheDocument(),
  );
  fireEvent.change(screen.getByTestId("clockin-pin"), {
    target: { value: pin },
  });
  fireEvent.click(screen.getByTestId("clockin-submit"));
}

beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* ignored */
  }
  stubNoGeo();
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
    global.fetch = vi.fn(async () => jr({ items: [EMP] }));
    renderPage();
    await lookupOnly();
    expect(screen.getByTestId("clockin-emp")).toHaveTextContent(/Ada/);
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
    stubFetch({ ...BASE_PUNCH, warnings: ["attendance_recompute_failed"] });
    renderPage();
    await clockInFlow();
    await waitFor(() =>
      expect(screen.getByTestId("clockin-recompute-warning")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("clockin-success")).not.toBeInTheDocument();
  });

  it("sends latitude, longitude and accuracy when a fix is available", async () => {
    stubGeo({ kind: "ok", accuracy: 12 });
    const sent: { body?: Record<string, unknown> } = {};
    stubFetch({ ...BASE_PUNCH, geofence_result: "inside" }, sent);
    renderPage();
    await clockInFlow();
    await waitFor(() => expect(sent.body).toBeDefined());
    expect(sent.body?.latitude).toBeCloseTo(-33.9249, 4);
    expect(sent.body?.longitude).toBeCloseTo(18.4241, 4);
    expect(sent.body?.gps_accuracy_m).toBe(12);
  });

  it("still clocks in, without location, when permission is denied", async () => {
    stubGeo({ kind: "denied" });
    const sent: { body?: Record<string, unknown> } = {};
    stubFetch({ ...BASE_PUNCH, geofence_result: "unavailable" }, sent);
    renderPage();
    await clockInFlow();
    await waitFor(() => expect(sent.body).toBeDefined());
    expect(sent.body?.employee_id).toBe(EMP.id);
    expect(sent.body).not.toHaveProperty("latitude");
    expect(sent.body).not.toHaveProperty("longitude");
    expect(sent.body).not.toHaveProperty("gps_accuracy_m");
  });

  it("clocks in when the browser has no geolocation at all", async () => {
    stubNoGeo();
    stubFetch(BASE_PUNCH);
    renderPage();
    await clockInFlow();
    await waitFor(() =>
      expect(screen.getByTestId("clockin-success")).toBeInTheDocument(),
    );
  });

  it("warns before submitting when the fix is poor", async () => {
    stubGeo({ kind: "ok", accuracy: 65 });
    stubFetch(BASE_PUNCH);
    renderPage();
    await lookupOnly();
    await waitFor(() =>
      expect(screen.getByTestId("clockin-accuracy-warning")).toBeInTheDocument(),
    );
    expect(screen.getByText(/about 65 m/i)).toBeInTheDocument();
  });

  it("does not warn when the fix is accurate", async () => {
    stubGeo({ kind: "ok", accuracy: 12 });
    stubFetch(BASE_PUNCH);
    renderPage();
    await lookupOnly();
    expect(
      screen.queryByTestId("clockin-accuracy-warning"),
    ).not.toBeInTheDocument();
  });

  it("shows site, accuracy and an inside verdict after clocking in", async () => {
    stubGeo({ kind: "ok", accuracy: 12 });
    stubFetch({
      ...BASE_PUNCH,
      site_name: "Hotel Branch",
      geofence_result: "inside",
      geofence_reason: "within_geofence",
      location: {
        latitude: "-33.924900",
        longitude: "18.424100",
        gps_accuracy_m: "12.00",
        distance_m: "4.50",
        captured_at: "2026-11-10T08:00:00Z",
      },
    });
    renderPage();
    await clockInFlow();
    const v = await screen.findByTestId("clockin-verdict");
    expect(v).toHaveTextContent(/Hotel Branch/);
    expect(v).toHaveTextContent(/accurate to 12 m/i);
    expect(v).toHaveTextContent(/Inside authorised area/i);
  });

  it("shows distance from the site when outside the geofence", async () => {
    stubGeo({ kind: "ok", accuracy: 8 });
    stubFetch({
      ...BASE_PUNCH,
      site_name: "Bellville",
      geofence_result: "outside",
      geofence_reason: "outside_geofence",
      location: {
        latitude: "-33.923900",
        longitude: "18.424100",
        gps_accuracy_m: "8.00",
        distance_m: "19152.30",
        captured_at: "2026-11-10T08:00:00Z",
      },
    });
    renderPage();
    await clockInFlow();
    const v = await screen.findByTestId("clockin-verdict");
    expect(v).toHaveTextContent(/Bellville/);
    expect(v).toHaveTextContent(/19152 m from site/i);
    expect(v).toHaveTextContent(/Outside the authorised area/i);
  });

  it("explains a refused location under the verdict", async () => {
    stubGeo({ kind: "denied" });
    stubFetch({
      ...BASE_PUNCH,
      site_name: "Hotel Branch",
      geofence_result: "unavailable",
      geofence_reason: "punch_coordinates_missing",
    });
    renderPage();
    await clockInFlow();
    const v = await screen.findByTestId("clockin-verdict");
    expect(v).toHaveTextContent(/No location recorded/i);
    expect(v).toHaveTextContent(/permission was refused/i);
  });

  it("blames the site, not the phone, when the site has no radius", async () => {
    stubGeo({ kind: "ok", accuracy: 12 });
    stubFetch({
      ...BASE_PUNCH,
      site_name: "Hotel Branch",
      geofence_result: "unavailable",
      geofence_reason: "site_radius_not_configured",
      location: {
        latitude: "-33.924900",
        longitude: "18.424100",
        gps_accuracy_m: "12.00",
        distance_m: null,
        captured_at: "2026-11-10T08:00:00Z",
      },
    });
    renderPage();
    await clockInFlow();
    const v = await screen.findByTestId("clockin-verdict");
    expect(v).toHaveTextContent(/This site has no location configured/i);
    expect(v).not.toHaveTextContent(/No location recorded/i);
    expect(v).toHaveTextContent(/accurate to 12 m/i);
  });

  it("reads accuracy and distance from the nested location object", async () => {
    stubGeo({ kind: "ok", accuracy: 12 });
    stubFetch({
      ...BASE_PUNCH,
      site_name: "Bellville",
      geofence_result: "outside",
      geofence_reason: "outside_geofence",
      location: {
        latitude: "-33.923900",
        longitude: "18.424100",
        gps_accuracy_m: "9.00",
        distance_m: "19152.30",
        captured_at: "2026-11-10T08:00:00Z",
      },
    });
    renderPage();
    await clockInFlow();
    const v = await screen.findByTestId("clockin-verdict");
    expect(v).toHaveTextContent(/accurate to 9 m/i);
    expect(v).toHaveTextContent(/19152 m from site/i);
  });

  it("falls back to the locally measured accuracy when no fix is returned", async () => {
    stubGeo({ kind: "ok", accuracy: 7 });
    stubFetch({
      ...BASE_PUNCH,
      site_name: "Hotel Branch",
      geofence_result: "inside",
      geofence_reason: "within_geofence",
      location: null,
    });
    renderPage();
    await clockInFlow();
    const v = await screen.findByTestId("clockin-verdict");
    expect(v).toHaveTextContent(/accurate to 7 m/i);
  });

  // -------------------------------------------------------------------------
  // Non-biometric fallback (privacy policy section 4)
  // -------------------------------------------------------------------------

  it("offers the PIN alternative on the clock-in screen itself", async () => {
    // Section 4 requires the alternative to be genuinely available. An option
    // an employee can only discover from HR documentation is not.
    stubFetch(BASE_PUNCH);
    renderPage();
    await lookupOnly();
    expect(screen.getByText("Use a PIN instead")).toBeInTheDocument();
  });

  it("sends method=pin and the PIN, with no photo, in PIN mode", async () => {
    stubGeo({ kind: "ok", accuracy: 12 });
    const sent: { body?: Record<string, unknown> } = {};
    stubFetch({ ...BASE_PUNCH, method: "pin" }, sent);
    renderPage();
    await pinFlow("481920");
    await waitFor(() => expect(sent.body).toBeDefined());
    expect(sent.body?.method).toBe("pin");
    expect(sent.body?.pin).toBe("481920");
    expect(sent.body).not.toHaveProperty("photo_base64");
  });

  it("does not require the camera in PIN mode", async () => {
    stubFetch({ ...BASE_PUNCH, method: "pin" });
    renderPage();
    await pinFlow("481920");
    await waitFor(() =>
      expect(screen.getByTestId("clockin-success")).toBeInTheDocument(),
    );
  });

  it("cannot submit a PIN punch with an empty PIN", async () => {
    stubFetch(BASE_PUNCH);
    renderPage();
    await lookupOnly();
    fireEvent.click(screen.getByText("Use a PIN instead"));
    await waitFor(() =>
      expect(screen.getByTestId("clockin-pin")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("clockin-submit")).toBeDisabled();
  });

  it("tells the employee to ask HR when no PIN is set", async () => {
    stubFetchPunchError(
      400,
      "pin_not_set",
      "No attendance PIN has been set for this employee. Ask HR to set one.",
    );
    renderPage();
    await pinFlow("481920");
    await waitFor(() =>
      expect(screen.getByTestId("clockin-error")).toHaveTextContent(
        /Ask HR to set one/i,
      ),
    );
  });

  it("explains a lockout instead of leaving the employee stuck", async () => {
    stubFetchPunchError(423, "pin_locked", "PIN is locked for 15 minutes.");
    renderPage();
    await pinFlow("481920");
    await waitFor(() =>
      expect(screen.getByTestId("clockin-error")).toHaveTextContent(
        /Too many incorrect PINs|locked/i,
      ),
    );
  });

  it("switches back to the camera and releases it when leaving PIN mode", async () => {
    stubFetch(BASE_PUNCH);
    renderPage();
    await lookupOnly();
    fireEvent.click(screen.getByText("Use a PIN instead"));
    await waitFor(() =>
      expect(screen.getByTestId("clockin-pin")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByText("Use the camera instead"));
    await waitFor(() =>
      expect(screen.getByTestId("clockin-start-camera")).toBeInTheDocument(),
    );
  });
});