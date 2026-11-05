"""Append P1 record to docs/FRONTEND_STATE.md."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "docs" / "FRONTEND_STATE.md"
src = P.read_text(encoding="utf-8")

if "## Visual polish P1 (shipped)" in src:
    print("P1 section already present")
else:
    section = """
## Visual polish P1 (shipped)

### Theme (single source of colours, fonts, radius, shadows, spacing)
- `frontend/src/theme.ts` — Mantine `createTheme`. Light-only this pass
  (`defaultColorScheme="light"` in `main.tsx`).
- Palettes: `navy` (primary, deep #0B3D5C), `accent` (warm #C45F22),
  `approved` (green), `pending` (amber), `problem` (red). `gray`
  inherited from Mantine defaults for `inactive`.
- Fonts: Inter (system stack fallback; no npm font package added).
- Radius: `md` (12px) global. Shadows: `sm` on Card, `md` on Modal.
- `theme/components` overrides: `Button`, `Paper`, `Card`, `Badge`,
  `Modal`, `Alert`, `Table` (uppercase th, `F7F8FA` background, no
  stripes, hover-on).
- `frontend/src/theme/colors.ts` — semantic colour aliases used by
  every page (`colors.approved`, `colors.pending`, `colors.problem`,
  `colors.inactive`, `colors.info`, `colors.warning`, `colors.accent`).
  No page writes a literal colour name.
- Previous `theme.ts` preserved as `theme.backup.ts` (unused; can be
  deleted with `git rm frontend/src/theme.backup.ts` if not needed).

### App shell
- `frontend/src/shell/AppShell.tsx` — Mantine `AppShell` with:
  - Left `Navbar` (248px), grouped by section (Attendance / People /
    Payroll / Setup / Audit), icon + label per item, active-state
    styling via theme tokens.
  - Header (56px) with brand text + user menu (role label + logout).
  - Mobile: hamburger toggles `Navbar`.
- `frontend/src/shell/nav.ts` — new grouped `buildNav` returns
  `NavGroup[]` (`label`, `items[]`). Same permission gates as before;
  Home gated on `self_view`; Clock-in gated on `attendance_view`;
  Payslips gated on `payslip_view`.
- `frontend/src/shell/nav.test.ts` — rewritten (6 tests, grouped shape).

### Layout primitives (available for page adoption in P2/P3)
- `components/layout/Icon.tsx` — 12 inline SVG icons (no npm
  dependency added).
- `components/layout/PageHeader.tsx` — title + optional subtitle +
  actions slot.
- `components/layout/EmptyState.tsx` — centered dimmed message.
- `components/layout/TableSkeleton.tsx` — header + row skeletons.

### Colour sweep
- 24 `*.tsx` files: literal `color="red|green|orange|yellow|blue|gray"`
  replaced with `color={colors.X}`. `import { colors } from
  "<rel>/theme/colors"` added to each.

### Verification
- tsc clean.
- 120/120 vitest green (23 files).
- Browser check pending user confirmation.

### Notes / deferred
- Dark mode is a follow-up pass (palette tuned for light).
- Tenant name in header: `UserMeOut` has no tenant-name field.
  Header shows "Payroll" (appName). Real tenant name needs a `/tenant`
  endpoint (backend gap, out of P1 scope).
- `PageHeader` adoption in individual pages is a P2/P3 concern — the
  theme overrides apply without markup changes.
"""
    P.write_text(src + section, encoding="utf-8")
    print("P1 section appended to FRONTEND_STATE.md")