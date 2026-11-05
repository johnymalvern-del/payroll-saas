"""Job B fix v4:
1. previewEmployeeAsOf throws plain Error (no PayPeriodsApiError arity guess).
2. Page 403 detection regex -> /403|forbidden|permission/i.
3. Date-picker test: waitFor instead of setTimeout.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

# ---- 1. payPeriods.ts: previewEmployeeAsOf -> plain Error ----
pp = SRC / "api" / "payPeriods.ts"
s = pp.read_text(encoding="utf-8")

# find the previewEmployeeAsOf body and replace its error block
pat = re.compile(
    r"(export async function previewEmployeeAsOf\([\s\S]*?if \(!res\.ok\) \{)"
    r"[\s\S]*?"
    r"(return \(await res\.json\(\)\) as PreviewEmployeeAsOfOut;)",
    re.M,
)
m = pat.search(s)
if not m:
    raise SystemExit("FATAL: previewEmployeeAsOf body not matched")

replacement = (
    m.group(1)
    + "\n    const errBody = (await res.json().catch(() => ({}))) as {\n"
      "      error?: { code?: string; message?: string; details?: unknown };\n"
      "    };\n"
      "    const apiMsg =\n"
      "      errBody.error?.message ??\n"
      "      (res.status === 403 ? \"forbidden\" : `HTTP ${res.status}`);\n"
      "    const apiCode = errBody.error?.code ?? \"http_error\";\n"
      "    const e = new Error(apiMsg) as Error & {\n"
      "      code?: string;\n"
      "      status?: number;\n"
      "      details?: unknown;\n"
      "    };\n"
      "    e.code = apiCode;\n"
      "    e.status = res.status;\n"
      "    e.details = errBody.error?.details ?? null;\n"
      "    throw e;\n"
      "  }\n"
    + m.group(2)
)
s = s[:m.start()] + replacement + s[m.end():]
pp.write_text(s, encoding="utf-8")
print("payPeriods.ts: previewEmployeeAsOf throws plain Error with .code/.status/.details")

# ---- 2. Page 403 detection regex ----
page = SRC / "pages" / "PayslipSoFarPage.tsx"
s = page.read_text(encoding="utf-8")

old = '''        <Alert color={colors.problem} data-testid="payslip-error">
          {(estimate.error as Error)?.message?.includes("403")
            ? "You do not have permission to view payroll previews."
            : "Could not load estimate."}
        </Alert>'''
new = '''        <Alert color={colors.problem} data-testid="payslip-error">
          {isPermissionError(estimate.error)
            ? "You do not have permission to view payroll previews."
            : "Could not load estimate."}
        </Alert>'''
if old not in s:
    raise SystemExit("FATAL: page error block not matched")
s = s.replace(old, new, 1)

# add helper before component
helper_anchor = "function todayISO(): string {"
helper = '''function isPermissionError(err: unknown): boolean {
  if (!err) return false;
  const e = err as Error & { status?: number; code?: string };
  if (e.status === 403) return true;
  if (e.code === "forbidden") return true;
  const msg = e.message ?? "";
  return /403|forbidden|permission/i.test(msg);
}

'''
if "function isPermissionError" not in s:
    s = s.replace(helper_anchor, helper + helper_anchor, 1)
    print("page: isPermissionError helper added")

page.write_text(s, encoding="utf-8")
print("page: 403 detection extended")

# ---- 3. Test: date picker waitFor ----
test = SRC / "pages" / "PayslipSoFarPage.test.tsx"
s = test.read_text(encoding="utf-8")

old_test = '''  it("date picker fires new fetch when changed", async () => {
    const calls: string[] = [];
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      calls.push(url);
      if (url.includes("/preview/")) return jr(baseEstimate());
      return jr(PERIOD);
    });
    renderPage();
    const input = await screen.findByTestId("payslip-asof-input");
    fireEvent.change(input, { target: { value: "2026-11-10" } });
    await new Promise((r) => setTimeout(r, 150));
    const previews = calls.filter((u) => u.includes("/preview/"));
    expect(previews.some((u) => u.includes("as_of=2026-11-10"))).toBe(true);
  });'''
new_test = '''  it("date picker fires new fetch when changed", async () => {
    const calls: string[] = [];
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      calls.push(url);
      if (url.includes("/preview/")) return jr(baseEstimate());
      return jr(PERIOD);
    });
    renderPage();
    const input = await screen.findByTestId("payslip-asof-input");
    fireEvent.change(input, { target: { value: "2026-11-10" } });
    await waitFor(
      () => {
        const previews = calls.filter((u) => u.includes("/preview/"));
        expect(previews.some((u) => u.includes("as_of=2026-11-10"))).toBe(true);
      },
      { timeout: 1500 },
    );
  });'''
if old_test not in s:
    raise SystemExit("FATAL: date picker test block not matched")
s = s.replace(old_test, new_test, 1)

# ensure waitFor is imported
if "waitFor" not in s.split("\n")[0] and "waitFor," not in s[:500]:
    s = s.replace(
        'import { cleanup, fireEvent, render, screen } from "@testing-library/react";',
        'import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";',
        1,
    )
    print("test: waitFor imported")

test.write_text(s, encoding="utf-8")
print("test: date picker test uses waitFor")