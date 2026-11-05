"""P1c: replace literal color="X" with colors.Y across all *.tsx, add import."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

MAP = {
    "red": "problem",
    "green": "approved",
    "orange": "pending",
    "yellow": "warning",
    "blue": "info",
    "gray": "inactive",
}

pat = re.compile(r'color="(red|green|orange|yellow|blue|gray)"')

def rel_import(file_path: Path) -> str:
    # path relative to src/, without filename
    rel = file_path.relative_to(SRC).parent
    depth = len(rel.parts)
    prefix = "../" * depth if depth else "./"
    return prefix + "theme/colors"

changed = 0
for p in SRC.rglob("*.tsx"):
    s = p.read_text(encoding="utf-8")
    if not pat.search(s):
        continue
    new = pat.sub(lambda m: f'color={{colors.{MAP[m.group(1)]}}}', s)
    if new == s:
        continue
    # add import if not present
    imp_rel = rel_import(p)
    imp_line = f'import {{ colors }} from "{imp_rel}";'
    if "from \"theme/colors\"" in new or "theme/colors" in new:
        pass  # already imported
    else:
        # insert after last import line
        lines = new.split("\n")
        last_import = -1
        for i, ln in enumerate(lines):
            if ln.lstrip().startswith("import "):
                last_import = i
        if last_import >= 0:
            lines.insert(last_import + 1, imp_line)
        else:
            lines.insert(0, imp_line)
        new = "\n".join(lines)
    p.write_text(new, encoding="utf-8")
    changed += 1
    print(f"patched {p.relative_to(SRC)}")

print(f"\nTotal files patched: {changed}")