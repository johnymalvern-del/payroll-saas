"""Add `from datetime import date` to payroll_pay_periods.py (missing after
job_b_fix). Idempotent."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "backend" / "app" / "api" / "v1" / "payroll_pay_periods.py"
s = P.read_text(encoding="utf-8")

if "from datetime import date" in s:
    print("already imported")
else:
    if "import uuid\n" in s:
        s = s.replace("import uuid\n", "import uuid\nfrom datetime import date\n", 1)
        P.write_text(s, encoding="utf-8")
        print("added `from datetime import date` after import uuid")
    elif "from typing import" in s:
        s = s.replace(
            "from typing import",
            "from datetime import date\nfrom typing import",
            1,
        )
        P.write_text(s, encoding="utf-8")
        print("added `from datetime import date` before typing import")
    else:
        raise SystemExit("FATAL: no anchor for datetime import")