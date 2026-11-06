"""Phase 1A fixes: remove bad import, clean unused imports, fix permission test."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"
FE = ROOT / "frontend" / "src"

# ---------- 1. Fix syntax error in test_intelligence_settings.py ----------
test = BE / "tests" / "test_intelligence_settings.py"
s = test.read_text(encoding="utf-8")
bad = "from app.db.tenant.models.adjustment import Adjustment if False else None  # noqa\n"
if bad in s:
    s = s.replace(bad, "", 1)
    test.write_text(s, encoding="utf-8")
    print("fixed: removed invalid import line from test_intelligence_settings.py")
elif "from app.db.tenant.models.adjustment import" in s:
    # Fallback: remove any line with that bad pattern
    lines = s.split("\n")
    lines = [ln for ln in lines if not ln.strip().startswith(
        "from app.db.tenant.models.adjustment import")]
    test.write_text("\n".join(lines), encoding="utf-8")
    print("fixed: removed any 'adjustment' import lines")
else:
    print("test_intelligence_settings.py: no bad import to remove")

# ---------- 2. Clean unused imports in IntelligenceSettingsPage.tsx ----------
page = FE / "pages" / "setup" / "IntelligenceSettingsPage.tsx"
s = page.read_text(encoding="utf-8")

# Remove "Divider," if present as a lone import line inside the mantine block
if re.search(r"^\s*Divider,\s*$", s, re.M):
    s = re.sub(r"^\s*Divider,\s*\n", "", s, count=1, flags=re.M)
    print("removed Divider import")
if re.search(r"^\s*Radio,\s*$", s, re.M):
    s = re.sub(r"^\s*Radio,\s*\n", "", s, count=1, flags=re.M)
    print("removed Radio import")

# Remove the type import IntelligenceSettings if unused
if "IntelligenceSettings," in s and "type IntelligenceSettings" in s:
    # Remove from the import braces
    s = s.replace(
        "  intelligenceApi,\n  type IntelligenceSettings,\n  type ModeChangeLog,\n  type WorkflowMode,\n",
        "  intelligenceApi,\n  type ModeChangeLog,\n  type WorkflowMode,\n",
        1,
    )
    print("removed IntelligenceSettings type import")

page.write_text(s, encoding="utf-8")
print("IntelligenceSettingsPage.tsx cleaned")

# ---------- 3. Fix permission test in IntelligenceSettingsPage.test.tsx ----------
ft = FE / "pages" / "setup" / "IntelligenceSettingsPage.test.tsx"
s = ft.read_text(encoding="utf-8")

# Replace the vi.mock block at top with a hoisted-variable version
old_mock = '''vi.mock("../../auth/useMe", () => ({
  useMe: () => ({
    data: {
      id: "u1", username: "admin", role: "payroll_admin",
      employee_id: null,
      permissions: ["intelligence_view", "intelligence_manage"],
      must_change_password: false, default_timezone: "Africa/Johannesburg",
    },
    isLoading: false, isError: false,
  }),
}));
'''
new_mock = '''const hoisted = vi.hoisted(() => ({
  permissions: ["intelligence_view", "intelligence_manage"] as string[],
}));

vi.mock("../../auth/useMe", () => ({
  useMe: () => ({
    data: {
      id: "u1", username: "admin", role: "payroll_admin",
      employee_id: null,
      permissions: hoisted.permissions,
      must_change_password: false, default_timezone: "Africa/Johannesburg",
    },
    isLoading: false, isError: false,
  }),
}));
'''
if old_mock not in s:
    print("WARN: original vi.mock block not matched verbatim — inspect file")
else:
    s = s.replace(old_mock, new_mock, 1)
    print("replaced vi.mock with vi.hoisted-variable version")

# Replace the entire failing test 7 with a hoisted-permission version
old_test7_start = '  it("permission denied hides write controls", async () => {'
old_test7_end_marker = "  });\n});\n"
# Find the last test block in the file
idx = s.find(old_test7_start)
if idx < 0:
    print("WARN: permission-denied test not found")
else:
    # Find its closing "  });\n"
    close_idx = s.find("\n  });", idx)
    if close_idx < 0:
        print("WARN: could not find test close")
    else:
        # Replace from old_test7_start through close_idx+"\n  });"
        new_test = '''  it("permission denied hides write controls", async () => {
    hoisted.permissions = ["intelligence_view"];
    mockAll();
    renderPage();
    await waitFor(() => expect(screen.getByTestId("intel-readonly-notice")).toBeInTheDocument());
    expect(screen.getByTestId("intel-save")).toBeDisabled();
    hoisted.permissions = ["intelligence_view", "intelligence_manage"];
  });
'''
        s = s[:idx] + new_test + s[close_idx + len("\n  });"):]
        print("replaced permission-denied test with hoisted-permissions version")

ft.write_text(s, encoding="utf-8")
print("test file patched")