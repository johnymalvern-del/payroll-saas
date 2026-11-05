"""Bundle 2 fixes: WorkPatternsPage missing Text import; BranchesPage test
has duplicate 'HQ' in code and name so getByText finds 2 elements."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

# ---- Fix 1: WorkPatternsPage.tsx — add Text import ----
wp = FRONTEND / "src" / "pages" / "setup" / "WorkPatternsPage.tsx"
s = wp.read_text(encoding="utf-8")

if "  Text," in s.split("\n")[0:20] or "Text," in s[:500]:
    print("WorkPatternsPage: Text may already be present, checking import")
else:
    old_import = (
        'import { Alert, Button, Group, Loader, Modal, Stack, Table, TextInput, Title, NumberInput, Checkbox } from "@mantine/core";'
    )
    new_import = (
        'import { Alert, Button, Checkbox, Group, Loader, Modal, NumberInput, Stack, Table, Text, TextInput, Title } from "@mantine/core";'
    )
    if old_import in s:
        s = s.replace(old_import, new_import, 1)
        wp.write_text(s, encoding="utf-8")
        print("WorkPatternsPage: import rewritten with Text (single-line form)")
    else:
        m = re.search(
            r'import\s*\{[^}]*\}\s*from\s*"@mantine/core";', s
        )
        if not m:
            raise SystemExit("FATAL: @mantine/core import not found in WorkPatternsPage")
        block = m.group(0)
        if re.search(r"\bText\b", block):
            print("WorkPatternsPage: Text already in import block")
        else:
            new_block = block.replace("TextInput", "Text, TextInput", 1)
            s = s.replace(block, new_block, 1)
            wp.write_text(s, encoding="utf-8")
            print("WorkPatternsPage: Text inserted before TextInput")

# ---- Fix 2: BranchesPage.test.tsx — change code to HQ1 ----
bp = FRONTEND / "src" / "pages" / "setup" / "BranchesPage.test.tsx"
s = bp.read_text(encoding="utf-8")
old = 'name: "HQ", code: "HQ"'
new = 'name: "HQ", code: "HQ1"'
if old in s:
    s = s.replace(old, new, 1)
    bp.write_text(s, encoding="utf-8")
    print("BranchesPage.test: code changed to HQ1 (no more duplicate getByText)")
elif 'code: "HQ1"' in s:
    print("BranchesPage.test: already HQ1")
else:
    # try looser replacement on code: "HQ"
    old2 = 'code: "HQ"'
    if old2 in s:
        s = s.replace(old2, 'code: "HQ1"', 1)
        bp.write_text(s, encoding="utf-8")
        print("BranchesPage.test: code changed to HQ1 (fallback)")
    else:
        raise SystemExit("FATAL: BranchesPage.test fixture pattern not found")