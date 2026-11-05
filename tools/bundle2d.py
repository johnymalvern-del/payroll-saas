"""Bundle 2D: App.tsx routes, tests for the 6 setup pages."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

# ---------- 1. App.tsx routes ----------
app = FRONTEND / "src" / "App.tsx"
s = app.read_text(encoding="utf-8")

IMPORTS = {
    'from "./pages/setup/SetupLayout"': 'import { SetupLayout } from "./pages/setup/SetupLayout";',
    'from "./pages/setup/SitesPage"': 'import { SitesPage } from "./pages/setup/SitesPage";',
    'from "./pages/setup/BranchesPage"': 'import { BranchesPage } from "./pages/setup/BranchesPage";',
    'from "./pages/setup/DepartmentsPage"': 'import { DepartmentsPage } from "./pages/setup/DepartmentsPage";',
    'from "./pages/setup/ShiftsPage"': 'import { ShiftsPage } from "./pages/setup/ShiftsPage";',
    'from "./pages/setup/WorkPatternsPage"': 'import { WorkPatternsPage } from "./pages/setup/WorkPatternsPage";',
    'from "./pages/setup/PublicHolidaysPage"': 'import { PublicHolidaysPage } from "./pages/setup/PublicHolidaysPage";',
}
for key, imp in IMPORTS.items():
    if key not in s:
        anchor = 'import { DevicesPage } from "./pages/setup/DevicesPage";'
        s = s.replace(anchor, anchor + "\n" + imp, 1)

# Replace `<Route path="setup" element={<PlaceholderPage title="Setup" phase="F-5" />} />`
# with a setup layout containing all tabs.
old_setup = '<Route path="setup" element={<PlaceholderPage title="Setup" phase="F-5" />} />'
new_setup = '''<Route path="setup" element={<SetupLayout />}>
            <Route index element={<SitesPage />} />
            <Route path="sites" element={<SitesPage />} />
            <Route path="branches" element={<BranchesPage />} />
            <Route path="departments" element={<DepartmentsPage />} />
            <Route path="shifts" element={<ShiftsPage />} />
            <Route path="work-patterns" element={<WorkPatternsPage />} />
            <Route path="public-holidays" element={<PublicHolidaysPage />} />
            <Route path="devices" element={<DevicesPage />} />
          </Route>'''
if old_setup in s:
    s = s.replace(old_setup, new_setup, 1)
    print("App.tsx: setup route expanded to layout with all tabs")
elif 'path="setup/sites"' in s:
    print("App.tsx: setup routes already present")
else:
    # existing setup/devices route must be removed to avoid duplicate
    s = s.replace('          <Route path="setup/devices" element={<DevicesPage />} />\n', '')
    old_devices = '<Route path="setup/devices" element={<DevicesPage />} />'
    if old_devices in s:
        s = s.replace(old_devices, new_setup, 1)
        print("App.tsx: replaced flat /setup/devices with layout block")
    else:
        print("WARN: no setup anchor found — flagged for review")

# Remove PlaceholderPage import if unused
if "PlaceholderPage" in s and s.count("PlaceholderPage") <= 2:
    s = s.replace('import { PlaceholderPage } from "./pages/PlaceholderPage";\n', '')

app.write_text(s, encoding="utf-8")

# ---------- 2. Tests ----------
TESTS = {
    "src/pages/setup/SitesPage.test.tsx": '''import { afterEach, describe, expect, it, vi } from "vitest";
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
''',
    "src/pages/setup/BranchesPage.test.tsx": '''import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { BranchesPage } from "./BranchesPage";
function jr(b: unknown, s = 200): Response { return new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } }); }
function renderPage() { const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } }); return render(<QueryClientProvider client={qc}><MantineProvider><BranchesPage /></MantineProvider></QueryClientProvider>); }
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe("BranchesPage", () => {
  it("lists branches", async () => {
    global.fetch = vi.fn(async () => jr({ items: [{ id: "b1", name: "HQ", code: "HQ", address: null, is_active: true, row_version: 1 }], next_cursor: null }));
    renderPage();
    await waitFor(() => expect(screen.getByText("HQ")).toBeInTheDocument());
  });
});
''',
    "src/pages/setup/DepartmentsPage.test.tsx": '''import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { DepartmentsPage } from "./DepartmentsPage";
function jr(b: unknown, s = 200): Response { return new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } }); }
function renderPage() { const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } }); return render(<QueryClientProvider client={qc}><MantineProvider><DepartmentsPage /></MantineProvider></QueryClientProvider>); }
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe("DepartmentsPage", () => {
  it("lists departments", async () => {
    global.fetch = vi.fn(async () => jr({ items: [{ id: "d1", name: "Ops", code: "OPS", parent_id: null, is_active: true, row_version: 1 }], next_cursor: null }));
    renderPage();
    await waitFor(() => expect(screen.getByText("Ops")).toBeInTheDocument());
  });
});
''',
    "src/pages/setup/ShiftsPage.test.tsx": '''import { afterEach, describe, expect, it, vi } from "vitest";
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
''',
    "src/pages/setup/WorkPatternsPage.test.tsx": '''import { afterEach, describe, expect, it, vi } from "vitest";
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
''',
    "src/pages/setup/PublicHolidaysPage.test.tsx": '''import { afterEach, describe, expect, it, vi } from "vitest";
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
''',
}
for rel, content in TESTS.items():
    p = FRONTEND / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"wrote {rel}")

print("\nBundle 2 files written.")