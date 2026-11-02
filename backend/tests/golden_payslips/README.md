# Golden payslip cases (Chapter 4H 4G-c)

One JSON file per accountant-reviewed payslip scenario. Each file
describes:

- **inputs**: employee, shift, shift rate rules, employee earnings and
  deductions, attendance days and segments, pay period
- **expected outputs**: gross, PAYE, net, per-line earnings, per-line
  deductions
- **review metadata**: `accountant_reviewed: true` plus `reviewed_by`
  and `reviewed_on` (both required when reviewed)

## Adding a case

1. Copy `case_001_placeholder.json` to `case_NNN_<scenario>.json`.
2. Fill in the fields described below.
3. Ask the accountant to fill in `expected` and mark the file with
   `accountant_reviewed: true` + `reviewed_by` + `reviewed_on`.
4. Update `docs/STATE.md` under "Payroll golden cases" — increment
   `Reviewed` and decrement `Unreviewed`.
5. Run `pytest tests/test_golden_payslips.py`.

## Statutory tables used by the framework

Because no live control-DB statutory tables are guaranteed at test time,
the framework applies **these fixed fake tables** to every case. Your
`expected` values must be computed against these:

- **PAYE brackets**: single bracket [0, 10000) at 18 percent; base_tax = 0
- **Rebates**: primary 1000, 65+ 0, 75+ 0
- **Thresholds**: 5000 for all three age bands
- **Medical credits**: 0
- **Retirement limit**: 10 percent of taxable income, annual cap 100000
- **UIF**: employee 1 percent, employer 1 percent, ceiling 100000 per month
- **SDL**: 1 percent, exemption threshold 50000 per year

The constants live in `backend/tests/test_golden_payslips.py`. If the
accountant's case needs different statutory values, extend the schema
with a statutory_tables section — a follow-up once real tables are
available.

## expected shape

The expected object has gross, paye, net (all strings), lines (a list
of {earning_type_code, amount}) and deductions (a list of
{deduction_type_name, amount}). All amounts are decimal strings.

Example: gross "800.00", paye "60.00", net "732.00"; one earning line
{earning_type_code: "hourly_normal", amount: "800.00"}; two deduction
lines {deduction_type_name: "PAYE", amount: "60.00"} and
{deduction_type_name: "UIF (employee)", amount: "8.00"}.

## employee / shift / etc. shapes

Follow the tenant model fields directly — the framework maps 1:1:

- employee: employee_code, first_name, last_name, hire_date, status,
  employee_type, pay_basis, pay_frequency, base_rate,
  contracted_weekly_hours
- shift: name, start_time ("HH:MM"), length_minutes,
  unpaid_break_minutes, overtime_requires_approval, max_shift_minutes,
  plus the other Shift columns (all optional with model defaults)
- shift_rate_rules: day_type, kind, tier, method, value
- employee_earnings: earning_type_code (must be in SYSTEM_TYPES),
  amount or rate, effective_from
- employee_deductions: deduction_type_code, amount, effective_from
- attendance_days: work_date, status, worked_minutes
- attendance_segments: local_date (must match an attendance_day's
  work_date), day_type, kind, tier, minutes, rate_method, rate_value
- pay_period: period_key, start_date, end_date, pay_date

## Skipping behaviour

- Unreviewed cases (accountant_reviewed: false) cause
  test_golden_unreviewed_cases_skipped_loudly to pytest.skip with the
  file names listed. Never silently green.
- Reviewed cases run against the real pipeline. If the framework finds
  zero reviewed cases, test_golden_reviewed_cases_pass also skips
  (with a distinct reason).