"""Milestone 2 closeout: frontend warnings + repo hygiene."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend" / "src"

# ============================================================
# 1. clockIn.ts — PunchOut gains warnings field
# ============================================================
api = FE / "api" / "clockIn.ts"
s = api.read_text(encoding="utf-8")
old = (
    "export type PunchOut = {\n"
    "  id: string;\n"
    "  effective_time: string;\n"
    "  status: string;\n"
    "  flags: string[];\n"
    "};\n"
)
new = (
    "export type PunchOut = {\n"
    "  id: string;\n"
    "  effective_time: string;\n"
    "  status: string;\n"
    "  flags: string[];\n"
    "  warnings?: string[];\n"
    "};\n"
)
if old not in s:
    raise SystemExit("FATAL: PunchOut block not matched")
api.write_text(s.replace(old, new, 1), encoding="utf-8")
print("[1/5] clockIn.ts: PunchOut.warnings added")

# ============================================================
# 2. strings.ts — clockIn.recomputeWarning
# ============================================================
st = FE / "lib" / "strings.ts"
s = st.read_text(encoding="utf-8")
anchor = '    cameraDenied: "Camera access denied or unavailable.",\n'
if anchor not in s:
    raise SystemExit("FATAL: cameraDenied anchor not found in strings.ts")
addition = (
    anchor
    + '    recomputeWarning: "Your punch was recorded, but attendance '
    'could not be updated. Please notify your administrator.",\n'
)
st.write_text(s.replace(anchor, addition, 1), encoding="utf-8")
print("[2/5] strings.ts: clockIn.recomputeWarning added")

# ============================================================
# 3. ClockInPage.tsx — warningMsg state + warning alert
# ============================================================
page = FE / "pages" / "ClockInPage.tsx"
s = page.read_text(encoding="utf-8")

# 3a. new state
old = '  const [successMsg, setSuccessMsg] = useState<string | null>(null);\n'
new = (
    old
    + '  const [warningMsg, setWarningMsg] = useState<string | null>(null);\n'
)
if old not in s:
    raise SystemExit("FATAL: successMsg state line not found")
s = s.replace(old, new, 1)

# 3b. resetDevice clears warningMsg
old = "    setSuccessMsg(null);\n    setErrorMsg(null);\n  };\n"
new = "    setSuccessMsg(null);\n    setWarningMsg(null);\n    setErrorMsg(null);\n  };\n"
if old not in s:
    raise SystemExit("FATAL: resetDevice successMsg block not found")
s = s.replace(old, new, 1)

# 3c. clockIn clears warningMsg on start
old = "    setErrorMsg(null);\n    setSuccessMsg(null);\n    try {\n      const photo ="
new = "    setErrorMsg(null);\n    setSuccessMsg(null);\n    setWarningMsg(null);\n    try {\n      const photo ="
if old not in s:
    raise SystemExit("FATAL: clockIn setErrorMsg block not found")
s = s.replace(old, new, 1)

# 3d. branch on warnings after successful submitPunch
old = (
    "      const t = new Date(out.effective_time).toLocaleTimeString();\n"
    '      setSuccessMsg(strings.clockIn.success.replace("{time}", t));\n'
    '      setPhase("success");\n'
)
new = (
    "      const t = new Date(out.effective_time).toLocaleTimeString();\n"
    "      if (out.warnings && out.warnings.length > 0) {\n"
    "        setWarningMsg(strings.clockIn.recomputeWarning);\n"
    "      } else {\n"
    '        setSuccessMsg(strings.clockIn.success.replace("{time}", t));\n'
    "      }\n"
    '      setPhase("success");\n'
)
if old not in s:
    raise SystemExit("FATAL: success message block not found")
s = s.replace(old, new, 1)

# 3e. render warning alert after success alert
old = (
    "        {successMsg && (\n"
    '          <Alert color={colors.approved} data-testid="clockin-success">\n'
    "            {successMsg}\n"
    "          </Alert>\n"
    "        )}\n"
)
new = (
    old
    + "        {warningMsg && (\n"
    + '          <Alert\n'
    + '            color={colors.pending}\n'
    + '            data-testid="clockin-recompute-warning"\n'
    + "          >\n"
    + "            {warningMsg}\n"
    + "          </Alert>\n"
    + "        )}\n"
)
if old not in s:
    raise SystemExit("FATAL: success alert block not found")
s = s.replace(old, new, 1)

page.write_text(s, encoding="utf-8")
print("[3/5] ClockInPage.tsx: warningMsg state + warning alert render")

# ============================================================
# 4. ClockInPage.test.tsx — 1 new test
# ============================================================
test = FE / "pages" / "ClockInPage.test.tsx"
s = test.read_text(encoding="utf-8")
if "clockin-recompute-warning" in s:
    print("[4/5] ClockInPage.test.tsx: already has warning test — skip")
else:
    new_test = '''

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
'''
    # Insert before the final closing "});" of the describe block
    marker = s.rstrip()
    if not marker.endswith("});"):
        raise SystemExit("FATAL: test file does not end with });")
    s = marker[: -len("});")].rstrip() + new_test + "\n});\n"
    test.write_text(s, encoding="utf-8")
    print("[4/5] ClockInPage.test.tsx: warning regression test added")

# ============================================================
# 5. .gitignore — exclude backend/var/ (runtime storage)
# ============================================================
gi = ROOT / ".gitignore"
s = gi.read_text(encoding="utf-8")
line = "backend/var/\n"
if line in s:
    print("[5/5] .gitignore: backend/var/ already excluded")
else:
    if not s.endswith("\n"):
        s += "\n"
    s += "\n# Runtime storage (LocalFileStorage writes here; never commit)\n" + line
    gi.write_text(s, encoding="utf-8")
    print("[5/5] .gitignore: backend/var/ added")

print("\nMilestone 2 closeout patch complete.")