"""Bundle 1B: write 2 tests + apply 4 edits (App.tsx, strings.ts, useMe.ts, config.ts)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

# ---------- 1. New test files ----------
TESTS = {
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
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
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
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("devices-add")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("devices-add"));
    fireEvent.change(screen.getByTestId("devices-site-id"), {
      target: { value: "11111111-1111-1111-1111-111111111111" },
    });
    fireEvent.change(screen.getByTestId("devices-name"), {
      target: { value: "N" },
    });
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

for rel, content in TESTS.items():
    p = FRONTEND / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"wrote {rel}")

# ---------- 2. App.tsx edits ----------
app = FRONTEND / "src" / "App.tsx"
s = app.read_text(encoding="utf-8")

# imports
if 'from "./pages/ClockInPage"' not in s:
    anchor = 'import { AttendanceSheetPage } from "./pages/AttendanceSheetPage";'
    if anchor in s:
        s = s.replace(
            anchor,
            anchor + '\nimport { ClockInPage } from "./pages/ClockInPage";',
            1,
        )
        print("App.tsx: ClockInPage import")
    else:
        # fall back: append imports before Routes
        m = re.search(r"\n<Routes>", s)
        if not m:
            raise SystemExit("App.tsx: Routes anchor missing")
        s = s[:m.start()] + '\nimport { ClockInPage } from "./pages/ClockInPage";' + s[m.start():]
        print("App.tsx: ClockInPage import (pre-Routes)")

if 'from "./pages/setup/DevicesPage"' not in s:
    anchor = 'import { ClockInPage } from "./pages/ClockInPage";'
    s = s.replace(
        anchor,
        anchor + '\nimport { DevicesPage } from "./pages/setup/DevicesPage";',
        1,
    )
    print("App.tsx: DevicesPage import")

# routes
if 'path="clock-in"' not in s:
    anchor = '<Route path="employees" element={<EmployeesPage />} />'
    if anchor not in s:
        raise SystemExit("App.tsx: employees route anchor missing")
    inject = anchor + '\n          <Route path="clock-in" element={<ClockInPage />} />'
    s = s.replace(anchor, inject, 1)
    print("App.tsx: /clock-in route added")

if 'path="setup/devices"' not in s:
    anchor = '<Route path="clock-in" element={<ClockInPage />} />'
    inject = anchor + '\n          <Route path="setup/devices" element={<DevicesPage />} />'
    s = s.replace(anchor, inject, 1)
    print("App.tsx: /setup/devices route added")

app.write_text(s, encoding="utf-8")

# ---------- 3. strings.ts edits ----------
st = FRONTEND / "src" / "lib" / "strings.ts"
src = st.read_text(encoding="utf-8")

block = '''
  clockIn: {
    title: "Clock in",
    intro: "Enter this device's key once. It will be stored on this browser.",
    deviceKeyLabel: "Device key",
    deviceKeyPlaceholder: "Paste the key issued by HR",
    saveKey: "Save device key",
    resetDevice: "Reset this device",
    codeLabel: "Employee code",
    findEmployee: "Find employee",
    startCamera: "Start camera",
    stopCamera: "Stop camera",
    clockInNow: "Clock in",
    submitting: "Submitting\u2026",
    success: "Clocked in at {time}",
    noMatch: "No employee matches that code.",
    lookupFailed: "Lookup failed.",
    submitFailed: "Clock-in failed.",
    needPhoto: "Start the camera before clocking in.",
    cameraDenied: "Camera access denied or unavailable.",
  },
  devices: {
    title: "Devices",
    add: "Add device",
    addTitle: "New device",
    colName: "Name",
    colType: "Type",
    colStatus: "Status",
    colLastSeen: "Last seen",
    never: "\u2014",
    rotate: "Rotate key",
    siteIdLabel: "Site id",
    nameLabel: "Name",
    typeLabel: "Type",
    create: "Create",
    keyOnce: "Device key (shown once)",
    keyRotated: "New device key",
    keyCopyNow: "Copy this key now. It will not be shown again.",
    loadFailed: "Could not load devices.",
  },'''

if "clockIn:" not in src:
    m = re.search(r"export const strings = \{", src)
    if not m:
        raise SystemExit("strings.ts: strings export not found")
    src = src[:m.end()] + "\n" + block + "\n" + src[m.end():]
    print("strings.ts: clockIn + devices blocks added")
else:
    print("strings.ts: clockIn already present (skipped)")

st.write_text(src, encoding="utf-8")

# ---------- 4. useMe.ts / AuthContext.tsx: add default_timezone ----------
patched = False
for cand in (
    FRONTEND / "src" / "auth" / "useMe.ts",
    FRONTEND / "src" / "auth" / "AuthContext.tsx",
):
    if not cand.exists():
        continue
    t = cand.read_text(encoding="utf-8")
    if "default_timezone" in t:
        print(f"{cand.name}: default_timezone already present")
        patched = True
        break
    # try adding to a must_change_password adjacent type/interface
    m = re.search(r"(must_change_password:\s*boolean;)", t)
    if m:
        t = t[:m.end()] + "\n  default_timezone?: string | null;" + t[m.end():]
        cand.write_text(t, encoding="utf-8")
        print(f"{cand.name}: default_timezone added to Me type")
        patched = True
        break
    m = re.search(r"(must_change_password:\s*boolean,)", t)
    if m:
        t = t[:m.end()] + "\n  default_timezone?: string | null," + t[m.end():]
        cand.write_text(t, encoding="utf-8")
        print(f"{cand.name}: default_timezone added to Me type (comma)")
        patched = True
        break
if not patched:
    print("WARN: no useMe.ts/AuthContext.tsx type to extend — flagged for review")

# ---------- 5. config.ts: add getSiteTz ----------
cf = FRONTEND / "src" / "lib" / "config.ts"
src = cf.read_text(encoding="utf-8")
if "export function getSiteTz" in src:
    print("config.ts: getSiteTz already present")
else:
    m = re.search(r'(export const DEFAULT_SITE_TZ\s*=\s*"Africa/Johannesburg";\s*)', src)
    if not m:
        # broader fallback
        m = re.search(r"(export const DEFAULT_SITE_TZ[^\n]*\n)", src)
    if not m:
        raise SystemExit("config.ts: DEFAULT_SITE_TZ anchor missing")
    helper = (
        m.group(1)
        + "\n"
        + "export function getSiteTz(\n"
        + "  me?: { default_timezone?: string | null } | null,\n"
        + "): string {\n"
        + "  const tz = me?.default_timezone;\n"
        + "  return typeof tz === \"string\" && tz.length > 0 ? tz : DEFAULT_SITE_TZ;\n"
        + "}\n"
    )
    src = src.replace(m.group(1), helper, 1)
    cf.write_text(src, encoding="utf-8")
    print("config.ts: getSiteTz helper added")

print("\nBundle 1 files written.")