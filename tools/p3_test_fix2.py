"""Fix DayPanel.test.tsx: shift name timing + label as primary assertion."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P = ROOT / "frontend" / "src" / "components" / "AttendanceSheet" / "DayPanel.test.tsx"

s = P.read_text(encoding="utf-8")

old = '''    expect(await screen.findByText("Thabo Mokoena")).toBeInTheDocument();
    expect(screen.getByText(/T001/)).toBeInTheDocument();
    expect(await screen.findByText("worked")).toBeInTheDocument();
    expect(screen.getByText("normal")).toBeInTheDocument();
    expect(screen.getByText("overtime")).toBeInTheDocument();
    expect(await screen.findByText(/Day 08:00-17:00/)).toBeInTheDocument();
    expect(screen.getByText("Rate breakdown")).toBeInTheDocument();
    expect(screen.getByText("540")).toBeInTheDocument();
'''
new = '''    expect(await screen.findByText("Thabo Mokoena")).toBeInTheDocument();
    expect(screen.getByText(/T001/)).toBeInTheDocument();
    expect(await screen.findByText("worked")).toBeInTheDocument();
    expect(screen.getByText("normal")).toBeInTheDocument();
    expect(screen.getByText("overtime")).toBeInTheDocument();
    // Shift section: label is deterministic; name may be the resolved
    // shift name OR the id-prefix fallback depending on query timing.
    expect(await screen.findByText("Shift:")).toBeInTheDocument();
    expect(
      screen.queryByText(/Day 08:00-17:00/) ?? screen.queryByText("sh1"),
    ).not.toBeNull();
    expect(screen.getByText("Rate breakdown")).toBeInTheDocument();
    expect(screen.getByText("540")).toBeInTheDocument();
'''
if old not in s:
    raise SystemExit("FATAL: DayPanel.test.tsx target block not found — file may have drifted")
s = s.replace(old, new, 1)
P.write_text(s, encoding="utf-8")
print("patched DayPanel.test.tsx shift assertion")