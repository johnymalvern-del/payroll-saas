"""Job B extension: expose demo_values + unacknowledged_formulas on the
as_of response so the frontend can render its banners without a second call."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"

# ---- 1. payroll_runner.py: add 2 fields to base dict + cache settings ----
runner = BE / "app" / "services" / "payroll_runner.py"
s = runner.read_text(encoding="utf-8")

if "unacknowledged_formulas" in s and "demo_values" in s:
    print("runner: fields already present")
else:
    # cache settings once at top of the fn, before base dict
    old = "    base = {\n"
    if "unacknowledged_formulas" not in s:
        if "    base = {\n" in s:
            # insert settings cache + formula warnings before base dict
            pre = (
                "    _as_of_settings = _load_settings(db)\n"
                "    _as_of_formula_warnings = _formula_warnings(db)\n"
                "    base = {\n"
            )
            s = s.replace(old, pre, 1)
            print("runner: settings + formula_warnings cached before base dict")
        else:
            raise SystemExit("FATAL: `    base = {` not found")

    # add fields to base dict, right after available/reason_unavailable
    if '"unacknowledged_formulas"' not in s:
        old_fields = (
            '        "available": False,\n'
            '        "reason_unavailable": None,\n'
            '    }\n'
        )
        new_fields = (
            '        "available": False,\n'
            '        "reason_unavailable": None,\n'
            '        "unacknowledged_formulas": list(_as_of_formula_warnings),\n'
            '        "demo_values": bool(_as_of_settings.demo_values),\n'
            '    }\n'
        )
        if old_fields in s:
            s = s.replace(old_fields, new_fields, 1)
            print("runner: unacknowledged_formulas + demo_values added to base")
        else:
            raise SystemExit("FATAL: base dict fields not matched")

    runner.write_text(s, encoding="utf-8")

# ---- 2. schema: add 2 fields ----
schema = BE / "app" / "api" / "v1" / "payroll_pay_periods_schemas.py"
s = schema.read_text(encoding="utf-8")

if "unacknowledged_formulas: list[str]" in s and "demo_values: bool" in s:
    print("schema: fields already present")
else:
    old_tail = (
        "    available: bool = True\n"
        "    reason_unavailable: str | None = None\n"
        "    as_of: date | None = None\n"
    )
    new_tail = old_tail + (
        "    unacknowledged_formulas: list[str] = Field(default_factory=list)\n"
        "    demo_values: bool = False\n"
    )
    if old_tail in s:
        s = s.replace(old_tail, new_tail, 1)
        schema.write_text(s, encoding="utf-8")
        print("schema: unacknowledged_formulas + demo_values added")
    else:
        raise SystemExit("FATAL: schema tail not matched")