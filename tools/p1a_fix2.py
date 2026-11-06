"""Fix: Save must be clickable when Autonomous selected so it can open ack modal."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "setup" / "IntelligenceSettingsPage.tsx"
s = P.read_text(encoding="utf-8")

old = "  const canSave = canManage && modeChanged && reason.trim().length >= 3 && !needsAck;\n"
new = "  const canSave = canManage && modeChanged && reason.trim().length >= 3;\n"
if old not in s:
    raise SystemExit("FATAL: canSave line not matched — inspect file")
s = s.replace(old, new, 1)
P.write_text(s, encoding="utf-8")
print("canSave: removed !needsAck — Save enabled when mode changed + reason >= 3")