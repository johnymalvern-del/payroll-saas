"""Record F-3a closure in docs/FRONTEND_STATE.md."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "docs" / "FRONTEND_STATE.md"
src = P.read_text(encoding="utf-8")

anchor = "# Frontend state\n\n"
assert src.startswith(anchor), "unexpected FRONTEND_STATE.md header"

if "## F-3a closure" in src:
    print("F-3a closure note already present")
else:
    note = (
        "## F-3a closure (2026-11-03)\n\n"
        "- `frontend/src/pages/ExceptionsPage.test.tsx`: 17/17 passing\n"
        "  (`npx vitest run src/pages/ExceptionsPage.test.tsx --reporter=dot`).\n"
        "- Both ambiguous `getByText` calls noted in the handoff were already\n"
        "  scoped with `within(...)` on disk; verified green. No source change\n"
        "  was needed for F-3a.\n\n"
    )
    src = anchor + note + src[len(anchor):]
    P.write_text(src, encoding="utf-8")
    print("F-3a closure note added")