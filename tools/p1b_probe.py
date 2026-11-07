"""Phase 1B read-only inspection.

Reads files + queries the demo tenant's schema (no writes).
Prints exactly what I need to design the decision-record model
and evidence-snapshot mechanism without assuming anything.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"
FE = ROOT / "frontend" / "src"


def run(cmd, cwd=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=cwd or ROOT, shell=True, timeout=20)
        return (r.stdout or r.stderr).strip()
    except Exception as e:
        return f"ERR: {e}"


def section(title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def head(path, n=60):
    p = Path(path)
    if not p.exists():
        print(f"--- {path} --- NOT FOUND")
        return
    lines = p.read_text(encoding="utf-8").split("\n")
    print(f"--- {path} ({len(lines)} lines) ---")
    for ln in lines[:n]:
        print(ln)
    if len(lines) > n:
        print(f"... ({len(lines) - n} more lines)")


def grep(path, pattern, ctx=0):
    p = Path(path)
    if not p.exists():
        print(f"--- {path} --- NOT FOUND")
        return
    lines = p.read_text(encoding="utf-8").split("\n")
    for i, ln in enumerate(lines):
        if re.search(pattern, ln):
            lo = max(0, i - ctx)
            hi = min(len(lines), i + ctx + 1)
            for j in range(lo, hi):
                marker = ">>" if j == i else "  "
                print(f"{marker} {j+1:4}: {lines[j]}")
            if ctx:
                print()


# ============================================================
section("1. GIT + MIGRATION HEAD")
# ============================================================
print("head:", run("git rev-parse --short HEAD"))
print("dirty:", run("git status --short") or "(clean)")
versions = sorted((BE / "alembic" / "tenant" / "versions").glob("*.py"))
print(f"tenant migrations: {len(versions)} (last: {versions[-1].name})")

# ============================================================
section("2. EXISTING INTELLIGENCE MODEL (Phase 1A)")
# ============================================================
print("--- models/intelligence.py ---")
head(BE / "app" / "db" / "tenant" / "models" / "intelligence.py", n=200)

# ============================================================
section("3. EXISTING INTELLIGENCE SERVICE")
# ============================================================
head(BE / "app" / "services" / "intelligence_service.py", n=80)

# ============================================================
section("4. AUDIT — model + write_audit + DB immutability pattern")
# ============================================================
print("\n--- payroll_audit.py ---")
head(BE / "app" / "services" / "payroll_audit.py")

print("\n--- AuditLog model (platform.py) ---")
grep(BE / "app" / "db" / "tenant" / "models" / "platform.py",
     r"class AuditLog", ctx=25)

print("\n--- migrations that mention audit_log immutability (REVOKE/TRIGGER) ---")
for p in (BE / "alembic" / "tenant" / "versions").glob("*.py"):
    txt = p.read_text(encoding="utf-8")
    if "audit_log" in txt and ("REVOKE" in txt or "TRIGGER" in txt
                               or "trigger" in txt):
        print(f"\n--- {p.name} ---")
        for i, ln in enumerate(txt.split("\n"), 1):
            if any(k in ln for k in ("REVOKE", "TRIGGER", "trigger",
                                     "GRANT", "payroll_app", "audit_log")):
                print(f"{i:4}: {ln}")

# ============================================================
section("5. INTELLIGENCE ROUTER + API init")
# ============================================================
print("--- intelligence_settings.py (route decorators only) ---")
grep(BE / "app" / "api" / "v1" / "intelligence_settings.py",
     r"@router|^def ")

print("\n--- api/v1/__init__.py (intelligence import lines) ---")
grep(BE / "app" / "api" / "v1" / "__init__.py",
     r"intelligence", ctx=0)

# ============================================================
section("6. EMPLOYEE + SOURCE RECORD SHAPES (for FK design)")
# ============================================================
print("--- Employee model — field names only ---")
emp_src = (BE / "app" / "db" / "tenant" / "models" / "people.py").read_text(
    encoding="utf-8")
m = re.search(r"class Employee\([^)]+\):[\s\S]*?(?=\nclass )", emp_src)
if m:
    for ln in m.group(0).split("\n")[:50]:
        if ":" in ln and "Mapped" in ln:
            print(ln)

# ============================================================
section("7. FRONTEND INTELLIGENCE + NAV")
# ============================================================
print("--- api/intelligence.ts (exported funcs) ---")
grep(FE / "api" / "intelligence.ts", r"^export |^async function |^const \w+Api")

print("\n--- shell/nav.ts (nav item shape) ---")
grep(FE / "shell" / "nav.ts", r"audit|setup|intelligence|NavItem|PERMISSION_NAV",
     ctx=0)

print("\n--- frontend intelligence page structure ---")
grep(FE / "pages" / "setup" / "IntelligenceSettingsPage.tsx",
     r"^import |^export function |useQuery\(|useMutation\(")

# ============================================================
section("8. LIVE INTELLIGENCE TABLES + SUBSCRIBER STATE")
# ============================================================
try:
    from sqlalchemy import create_engine, text
    eng = create_engine(
        "postgresql+psycopg://payroll_test:payroll_test_dev_password"
        "@localhost:5432/tenant_tenant_demo",
        isolation_level="AUTOCOMMIT",
    )
    with eng.connect() as c:
        # Tables that exist
        print("--- intelligence_* tables on tenant_tenant_demo ---")
        for r in c.execute(text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname='public' AND tablename LIKE 'intelligence%' "
            "ORDER BY tablename"
        )):
            print(f"  {r[0]}")

        # Existing row counts (to confirm nothing in production)
        print("\n--- row counts ---")
        for t in ("intelligence_settings", "intelligence_workflow_mode",
                  "intelligence_mode_change_log", "intelligence_decision",
                  "intelligence_decision_override_reason"):
            try:
                n = c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                print(f"  {t}: {n} rows")
            except Exception as e:
                print(f"  {t}: ERR {e}")

        # Existing grants on audit_log (the pattern to copy for snapshots)
        print("\n--- grants on audit_log (existing immutability) ---")
        for r in c.execute(text(
            "SELECT grantee, privilege_type FROM information_schema.role_table_grants "
            "WHERE table_name = 'audit_log'"
        )):
            print(f"  {r[0]}: {r[1]}")

        # Existing triggers on audit_log
        print("\n--- triggers on audit_log ---")
        for r in c.execute(text(
            "SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger "
            "WHERE tgrelid = 'audit_log'::regclass AND NOT tgisinternal"
        )):
            print(f"  {r[0]}: {r[1][:200]}")

    eng.dispose()
except Exception as e:
    print("ERR:", e)

print("\n=== END PROBE ===")