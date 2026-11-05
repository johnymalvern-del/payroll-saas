"""Bundle 3: CSV export on the attendance sheet page.

- New: frontend/src/lib/csv.ts (RFC-4180 safe serialize + download)
- New: frontend/src/lib/csv.test.ts (6 unit tests)
- Edit: frontend/src/pages/AttendanceSheetPage.tsx (import, exportCsv
  handler, "Export CSV" button in the header Group)
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

# ---------- 1. New files ----------
NEW = {
    "src/lib/csv.ts": '''export function toCsv(rows: string[][]): string {
  return rows.map((r) => r.map(escapeCell).join(",")).join("\\r\\n");
}

function escapeCell(v: string): string {
  if (v === null || v === undefined) return "";
  const s = String(v);
  if (/[",\\r\\n]/.test(s)) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

export function downloadCsv(filename: string, content: string): void {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
''',

    "src/lib/csv.test.ts": '''import { describe, expect, it } from "vitest";
import { toCsv } from "./csv";

describe("toCsv", () => {
  it("empty rows yields empty string", () => {
    expect(toCsv([])).toBe("");
  });

  it("joins simple rows with CRLF", () => {
    expect(toCsv([["a", "b"], ["c", "d"]])).toBe("a,b\\r\\nc,d");
  });

  it("quotes cells containing commas", () => {
    expect(toCsv([["a,b", "c"]])).toBe('"a,b",c');
  });

  it("escapes quotes inside cells", () => {
    expect(toCsv([['he said "hi"', "x"]])).toBe('"he said ""hi""",x');
  });

  it("quotes cells containing newlines", () => {
    expect(toCsv([["line1\\nline2"]])).toBe('"line1\\nline2"');
  });

  it("nulls become empty", () => {
    expect(toCsv([[null as unknown as string, "b"]])).toBe(",b");
  });
});
''',
}

for rel, content in NEW.items():
    p = FRONTEND / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"wrote {rel} ({len(content)} bytes)")

# ---------- 2. Edit AttendanceSheetPage.tsx ----------
page = FRONTEND / "src" / "pages" / "AttendanceSheetPage.tsx"
src = page.read_text(encoding="utf-8")

if 'from "../lib/csv"' in src:
    print("AttendanceSheetPage.tsx: csv import already present")
else:
    anchor = 'import { strings } from "../lib/strings";'
    if anchor not in src:
        # try any lib/strings import line
        m = re.search(r'import\s*\{[^}]*\}\s*from\s*"\.\./lib/strings";', src)
        if not m:
            raise SystemExit("FATAL: strings import anchor missing")
        src = src[:m.end()] + '\nimport { toCsv, downloadCsv } from "../lib/csv";' + src[m.end():]
    else:
        src = src.replace(
            anchor,
            anchor + '\nimport { toCsv, downloadCsv } from "../lib/csv";',
            1,
        )
    print("AttendanceSheetPage.tsx: csv import added")

if "const exportCsv = " in src:
    print("AttendanceSheetPage.tsx: exportCsv handler already present")
else:
    m = re.search(r"(\n  return \(\n    <Stack gap=\"md\">)", src)
    if not m:
        raise SystemExit("FATAL: return (<Stack gap=\"md\">) anchor missing")
    handler = '''
  const exportCsv = () => {
    const data = sheet.data;
    if (!data || data.items.length === 0) return;
    const headers = [
      "employee_code",
      "employee_name",
      "work_date",
      "status",
      "worked_minutes",
      "normal_minutes",
      "overtime_minutes",
      "flags",
      "open_exception_count",
      "locked",
      "reviewed",
    ];
    const rows: string[][] = [headers];
    for (const emp of data.items) {
      for (const d of emp.days) {
        rows.push([
          emp.employee_code,
          emp.employee_name,
          d.work_date,
          d.status ?? "",
          d.worked_minutes == null ? "" : String(d.worked_minutes),
          d.normal_minutes == null ? "" : String(d.normal_minutes),
          d.overtime_minutes == null ? "" : String(d.overtime_minutes),
          (d.flags ?? []).join(";"),
          String(d.open_exception_count),
          d.locked ? "true" : "false",
          d.reviewed ? "true" : "false",
        ]);
      }
    }
    const csv = toCsv(rows);
    const month = fromDate
      ? dayjs(fromDate).format("YYYY-MM")
      : dayjs().format("YYYY-MM");
    downloadCsv(`attendance-sheet-${month}.csv`, csv);
  };
'''
    src = src[:m.start(1)] + handler + src[m.start(1):]
    print("AttendanceSheetPage.tsx: exportCsv handler added")

if 'data-testid="attendance-export-csv"' in src:
    print("AttendanceSheetPage.tsx: export button already present")
else:
    title_line = "<Title order={2}>{strings.attendance.title}</Title>"
    if title_line not in src:
        raise SystemExit("FATAL: title anchor missing")
    button = (
        "\n        <Button"
        "\n          variant=\"default\""
        "\n          disabled={!sheet.data || sheet.data.items.length === 0}"
        "\n          onClick={exportCsv}"
        "\n          data-testid=\"attendance-export-csv\""
        "\n        >"
        "\n          Export CSV"
        "\n        </Button>"
    )
    src = src.replace(title_line, title_line + button, 1)
    print("AttendanceSheetPage.tsx: export button added")

page.write_text(src, encoding="utf-8")
print("\nBundle 3 files written.")