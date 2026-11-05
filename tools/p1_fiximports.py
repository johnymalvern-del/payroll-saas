"""P1 fix v2: find `import { colors } from "...theme/colors";` on ANY line
(including indented inside an import block), remove it, and reinsert after
the true last import statement."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

INJECT = re.compile(r'^[ \t]*import \{ colors \} from "([^"]+theme/colors)";[ \t]*\n', re.M)
IMPORT_LINE = re.compile(r'^import\s')
SINGLE_LINE_END = re.compile(r'from\s*"[^"]+"\s*;?\s*$')
SIDE_EFFECT = re.compile(r'^import\s+"[^"]+"\s*;?\s*$')
BLOCK_END = re.compile(r'^\}\s*from\s*"[^"]+"\s*;?\s*$')

fixed = 0
for p in SRC.rglob("*.tsx"):
    s = p.read_text(encoding="utf-8")
    m = INJECT.search(s)
    if not m:
        continue
    imp_path = m.group(1)
    s = s[:m.start()] + s[m.end():]

    lines = s.split("\n")
    last_end = -1
    in_block = False
    for i, ln in enumerate(lines):
        stripped = ln.rstrip()
        if not in_block and IMPORT_LINE.match(stripped):
            if SIDE_EFFECT.match(stripped) or SINGLE_LINE_END.search(stripped):
                last_end = i
            elif stripped.endswith("{"):
                in_block = True
        elif in_block:
            if BLOCK_END.search(stripped):
                last_end = i
                in_block = False

    insert_line = f'import {{ colors }} from "{imp_path}";'
    if last_end >= 0:
        lines.insert(last_end + 1, insert_line)
    else:
        lines.insert(0, insert_line)

    p.write_text("\n".join(lines), encoding="utf-8")
    fixed += 1
    print(f"fixed {p.relative_to(SRC)}")

print(f"\nTotal files fixed: {fixed}")