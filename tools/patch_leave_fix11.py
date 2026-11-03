"""L2d fix11: add leave_request_id + system_generated columns to Adjustment
model (attendance.py). Migration ten_0024 already created these columns in
the tenant DB; the SQLAlchemy model was never updated to match. Python
attribute error, not a DB error — DB is already correct.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "backend" / "app" / "db" / "tenant" / "models" / "attendance.py"

src = MODEL.read_text(encoding="utf-8")

# --- 1. Verify imports ---
needs_import = []
if not re.search(r"\bBoolean\b", src.split("class ")[0]):
    needs_import.append("Boolean")
if not re.search(r"\btext\b", src.split("class ")[0]):
    needs_import.append("text")
if needs_import:
    m = re.search(r"from sqlalchemy import \(([^)]*)\)", src, re.S)
    if m:
        existing = m.group(1)
        add = ", ".join(needs_import)
        src = src[:m.start(1)] + existing.rstrip() + ("" if existing.rstrip().endswith(",") else ",") + "\n    " + add + ",\n" + src[m.end(1):]
        print(f"attendance.py: added imports {needs_import} (paren form)")
    else:
        m = re.search(r"from sqlalchemy import ([^\n(]+)", src)
        if m:
            src = src[:m.start(1)] + m.group(1) + ", " + ", ".join(needs_import) + src[m.end(1):]
            print(f"attendance.py: added imports {needs_import} (line form)")
        else:
            raise SystemExit("FATAL: cannot find sqlalchemy import")
else:
    print("attendance.py: imports Boolean + text already present")

# --- 2. Insert two columns before created_at in Adjustment ---
# Anchor: the unique 'created_at' inside class Adjustment (not other classes).
adj_start = src.find("class Adjustment(Base):")
if adj_start < 0:
    raise SystemExit("FATAL: class Adjustment not found")
next_class = src.find("\nclass ", adj_start + 1)
if next_class < 0:
    next_class = len(src)
adj_body = src[adj_start:next_class]

anchor = (
    "    created_at: Mapped[datetime] = mapped_column(\n"
    "        DateTime(timezone=True), nullable=False, server_default=func.now()\n"
    "    )\n"
)
if "    leave_request_id: Mapped" in adj_body and "    system_generated: Mapped" in adj_body:
    print("Adjustment: both columns already present")
else:
    if anchor not in adj_body:
        raise SystemExit("FATAL: Adjustment created_at anchor not found")
    inject = (
        "    leave_request_id: Mapped[uuid.UUID | None] = mapped_column(\n"
        "        UUID(as_uuid=True),\n"
        "        ForeignKey(\"leave_request.id\", ondelete=\"SET NULL\"),\n"
        "        nullable=True,\n"
        "    )\n"
        "    system_generated: Mapped[bool] = mapped_column(\n"
        "        Boolean(), nullable=False, server_default=text(\"false\")\n"
        "    )\n"
    )
    adj_new = adj_body.replace(anchor, inject + anchor, 1)
    src = src[:adj_start] + adj_new + src[next_class:]
    MODEL.write_text(src, encoding="utf-8")
    print("Adjustment: leave_request_id + system_generated columns added")

# --- 3. Verify ---
check = MODEL.read_text(encoding="utf-8")
adj_start2 = check.find("class Adjustment(Base):")
next2 = check.find("\nclass ", adj_start2 + 1)
if next2 < 0:
    next2 = len(check)
adj2 = check[adj_start2:next2]
print("=== Adjustment body columns ===")
for m2 in re.finditer(r"^    ([a-z_]+):\s+Mapped", adj2, re.M):
    print(f"  {m2.group(1)}")