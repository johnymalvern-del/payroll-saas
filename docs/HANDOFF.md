# Payroll System — Handoff (Chapter 4 closed, 2026-10-30)

## 1. Project in 5 lines
- Payroll + attendance system for small South African employers.
- For SMB owners and their HR/payroll_admin/manager/employee/auditor roles.
- Goal: cut payroll admin time by ~60% versus manual Excel.
- SA-first: ZAR, UIF, SDL, PAYE, BCEA-shaped attendance, POPIA-conscious data handling.
- Current target: backend feature-complete and fully tested by 1 December; demo story = clock in, manager fixes an exception, payroll run, payslip.

## 2. Environment
| Item | Value |
|---|---|
| Repo root | `C:\xampp\htdocs\Payroll` |
| Backend | `C:\xampp\htdocs\Payroll\backend` |
| Venv | `C:\xampp\htdocs\Payroll\.venv` — activate with `& .\.venv\Scripts\Activate.ps1` |
| Shell | Windows PowerShell 5.1, 4 GB RAM laptop |
| Python | 3.12 (venv) |
| Database | PostgreSQL 16 native (no Docker, no cloud) |
| psql binary | `C:\Program Files\PostgreSQL\16\bin\psql.exe` |
| DB roles | `payroll_admin` (runs migrations), `payroll_app` (runtime) |
| DBs | Control DB + one tenant DB per subscriber (`tenant_<slug>`) |
| Migrations | `backend/alembic/control/versions/` and `backend/alembic/tenant/versions/` |
| Alembic ini | `backend/alembic.ini` with `ini_section="tenant"` |
| Scripts folder | `C:\xampp\htdocs\Payroll\scripts\` (`.py` files gitignored) |
| Bundles folder | `C:\xampp\htdocs\Payroll\bundles\` |
| Tool | `python tools\apply_bundle.py` |
| Start API | `cd backend; python -m uvicorn app.main:app --reload --port 8000` |
| API base URL | `http://127.0.0.1:8000/api/v1` |
| Docs | `http://127.0.0.1:8000/docs` |
| Tenant routing | header `X-Tenant-Slug` or subdomain |

## 3. Stack and architecture rules
- FastAPI, synchronous SQLAlchemy 2.0, psycopg 3 driver.
- Alembic: separate chains for control DB and tenant DB.
- Pydantic v2 (`model_fields_set`, `model_validator`, `ConfigDict`).
- Argon2 for password hashing (weakened when `PAYROLL_TEST_FAST_HASH=1`; guard test asserts production defaults).
- No pandas, no Docker, no cloud dependencies.
- `TenantDep` and `TenantDbDep` travel as **values**, not ContextVars.
- `TenantCrypto` for encrypted columns.
- Interfaces with dev implementations refused in production: `StorageDep`, `JobRunnerDep`, `ScannerDep`.
- Every route declares `Depends(require_permission(...))`.
- Query params on unit-testable functions use `Annotated[X | None, Query()] = <real_default>`.

## 4. Binding rules
- Cursor envelope `{"items": [...], "next_cursor": ...}`, default limit 100, max 500.
- `row_version` optimistic locking; mismatch → `409 record_changed`.
- No hard deletes of payroll-relevant data; `is_active` / status. `DELETE` only when unreferenced, else `409 <thing>_in_use`.
- Every create/update/deactivate writes a **redacted** audit row.
- Scope helpers: `apply_scope`, `assert_in_scope`, branch/site variants. Fail-closed.
- Permission matrix in `app/core/permissions.py`; independent transcription in `tests/test_permissions.py`.
- Never invent tax or labour-law values.
- No biometric templates stored.
- Adjusted attendance days indistinguishable on the sheet.

## 5. How we work
- Bundles: `=== FILE: <path> ===` / content / `=== END FILE: <path> ===`. Save to `bundles\NNN.txt` (UTF-8), run `python tools\apply_bundle.py bundles\NNN.txt --commit "<msg>"`.
- `tools/apply_bundle.py`: parse + path-escape, backup to `.bundle_backup\<ts>\`, ast-parse every `.py`, `from app.main import app`, collect-only + pytest on **touched test files AND any test that imports a changed source file** (capped at 20). `do_commit` skips gitignored files (no more `scripts/*.py` staging failures).
- Flags: `--commit "<msg>"`, `--push`, `--rollback <ts>`, `--fast`, `--record-full-suite-pass`.
- 2 to 3 bundles per chapter. Full suite once at chapter end, then `--push`.
- Local commits per bundle. `--push` only at chapter end after `--record-full-suite-pass`.
- Decisions carry **defaults**; user overrides.
- **Stop rule**: two failures in a row on the same test → stop, ask.
- No leaked reasoning, no percentage estimates.
- Closing notes: files created/changed, commands, new tests count, assumptions, decisions needed.
- Timing stats at chapter end.

## 6. Milestone list
| Chapter | Status | Notes |
|---|---|---|
| 1A, 1B, 1C.1–1C.12 | Done, pushed | Tenancy, auth, employees, pay history, shifts, work patterns, public holidays, devices, punches |
| 2A, 2B, 2C | Done, pushed | `f768aec`, 692 tests, 2435 s |
| 3A — Leave + requests tables | Done locally, pushed | Migration `ten_0016` |
| 3B–3G — leave CRUD, approvals, sick notes, advances, grievances, `/me/*` | **Not started** | Deferred |
| 4A-bis — suite speed-up | Done | `scripts/4a_bis_patch*.py`, `test_security_argon2_guard.py`, `test_fastpath_diagnostic.py` |
| 4B — statutory loader | Done | `statutory_loader.py`, `scripts/load_statutory_tables.ps1` |
| 4C — pay schema | Done | Migration `ten_0017` |
| 4D-b — settings + types | Done | Migration `ten_0018` |
| 4D-c — employee earnings/deductions CRUD | Done, then rerouted via F3 | |
| 4E-i — formulas + ack | Done | Migration `ten_0019` |
| 4E-ii — TaxEngine + PAYE | Done | Commit `2bf842e` |
| 4E-iii-a — UIF, SDL, 11F | Done | |
| 4E-iii-b — pipeline + F7 floor | Done | |
| 4F-i — change requests | Done | Migration `ten_0020` |
| 4F-ii-1, 4F-ii-2 — writes rerouted + field endpoints | Done | |
| 4F-iii — system seed + import helper | Done | |
| 4G-a — pay periods + preview + finalise + reopen | Done | Commit `39ea616` |
| **4G-b — payslip endpoints + PDF** | **Done** | Commit `1bd042b` |
| **4G-c — STATE.md + framework + apply_bundle improvement + full suite + push** | **Done** | Commit `9e20b35` (final) |
| **Chapter 4 closed** | **Full suite: 970 passed, 2 skipped, 3205 s (53:25)** | `origin/main` = `9e20b35` |
| 5+ | Not started | Bank file, journals, EMP201/EMP501/IRP5 exports, POPIA subject-access, frontend, attendance-to-earnings integration |

## 7. Database state
### Control DB migrations
- `ctl_0001`: Initial control schema (`subscriber`, `platform_user`, `country_profile`, `public_holiday`, `control_audit_log`, legacy `statutory_table`)

### Tenant DB migrations
| # | Purpose |
|---|---|
| `ten_0001`…`ten_0014` | Tenancy seed, people, auth, org, devices, punches, attendance, exceptions |
| `ten_0015` | Attendance work surface |
| `ten_0016` | Leave + requests (9 tables) |
| `ten_0017` | Pay schema (11 tables + 3 employee columns) |
| `ten_0018` | `payroll_settings` |
| `ten_0019` | `payroll_settings.formula_acks` |
| `ten_0020` | `payroll_change_request` + 2 indexes + grants |

### Tables by area
- **Org**: `branch`, `site`, `department`
- **People**: `employee`, `employee_work_pattern`
- **Auth**: `user`, `session`, `password_reset`, `user_invite`
- **Attendance**: `punch`, `attendance_day`, `shift`, `shift_rate_rule`, `work_pattern`, `exception_item`, `adjustment`, `public_holiday_tenant`
- **Leave / requests**: `leave_type`, `leave_balance`, `leave_balance_ledger` (append-only), `leave_request`, `leave_request_day`, `leave_approval_step`, `leave_attachment`, `advance_request`, `grievance`
- **Pay**: `earning_type`, `deduction_type`, `employee_earning`, `employee_deduction`, `pay_period`, `payroll_run`, `payslip`, `payslip_line`, `advance_repayment`, `period_adjustment`, `period_reopen_log`, `payroll_settings`, `payroll_change_request`
- **Platform**: `audit_log` (append-only)

### New employee columns
`contracted_weekly_hours NUMERIC(5,2)`; `medical_scheme_members INTEGER NOT NULL DEFAULT 0`; `uif_exempt BOOLEAN NOT NULL DEFAULT FALSE`. `date_of_birth` pre-existed.

## 8. API map
All routers under `/api/v1`. Write gate shown; reads use PAYROLL_PREVIEW / PAYSLIP_VIEW / ATTENDANCE_VIEW.

| Area | Prefix | Write permission |
|---|---|---|
| register / auth | `/register`, `/auth` | public |
| company / branches / sites / departments | … | ORG_MANAGE |
| import_employees | `/employees/import` | EMPLOYEE_CRUD |
| employees | `/employees`, `/me` | EMPLOYEE_CRUD / SELF_VIEW |
| pay_history | `/pay-history` | PAY_RATE_REQUEST / PAY_RATE_APPROVE |
| users | `/users` | USER_MANAGE |
| audit_log | `/audit-log` | AUDIT_VIEW |
| shifts / shift_rate_rules | … | SHIFT_CONFIGURE |
| work_patterns / employee_work_patterns | … | ORG_MANAGE |
| public_holidays | `/public-holidays` | ORG_MANAGE |
| devices / punches | … | device auth |
| attendance / sheet / daily / mark_reviewed | `/attendance` | ATTENDANCE_VIEW / ATTENDANCE_ADJUST |
| exceptions | `/attendance/exceptions` | EXCEPTION_RESOLVE |
| adjustments | `/attendance/adjustments` | ATTENDANCE_ADJUST |
| payroll_settings | `/payroll/settings` | PAYROLL_FINALISE |
| payroll_types | `/payroll/earning-types`, `/payroll/deduction-types` | PAYROLL_FINALISE |
| payroll_employees | `/payroll/employees/{id}/earnings`, `/deductions` | writes **202-submit** change requests (PAY_RATE_REQUEST) |
| payroll_employee_fields | `/payroll/employees/{id}/fields` | PAY_RATE_REQUEST |
| payroll_formulas | `/payroll-formulas/readiness`, `/{code}/acknowledge` | PAYROLL_FINALISE |
| payroll_change_requests | `/payroll/change-requests` | PAY_RATE_REQUEST / PAY_RATE_APPROVE |
| payroll_system_types | `/payroll/earning-types/ensure-system` | PAYROLL_FINALISE |
| payroll_pay_periods | `/payroll/pay-periods` | PAYROLL_FINALISE / PAYROLL_REOPEN |
| payroll_payslips | `/payroll/payslips` | PAYSLIP_VIEW |

### New permissions in Chapter 4
None. All endpoints reuse the existing matrix.

## 9. Key modules
- **`attendance_engine.py`** — `recompute_day`, `build_day`, `ensure_days`.
- **`api/v1/exceptions.py`** — resolve, list, bulk_resolve.
- **`api/v1/adjustments.py`** — single, bulk (dry-run token), revert. Self-adjust 403, locked day 409.
- **`api/v1/sheet.py`** — monthly grid, daily list, `mark_reviewed` bulk.
- **`statutory_loader.py`** — `bootstrap_schema`, `apply_document`, `get_active_table`, `_default_engine` (prefers `control_session().get_bind()`), `_ensure_bootstrapped`.
- **`payroll_formulas.py`** — 6 pure earnings functions + `hourly_rate_from_monthly`. `FORMULA_REGISTRY`.
- **`payroll_tax.py`** — `TaxEngine` ABC, `RegularEarningsTaxEngine` (v1), `TaxTables`, `TaxResult`, `compute_age`, `load_tax_tables`.
- **`payroll_uif_sdl.py`** — `compute_uif_employee`, `compute_uif_employer` (ceiling-first), `compute_sdl`, `compute_retirement_limit`, `apply_retirement_limit`.
- **`payroll_pipeline.py`** — `run_pipeline(config, earnings, deductions, reimbursements) -> PayslipDraft`. Refusals as `draft.refused`.
- **`payroll_runner.py`** — `build_pipeline_config`, `run_preview`, `finalise`, `reopen`. `_COUNTRY_CODE` module var (`"ZA"` default, `"ZZ"` in tests). Only `calc_method='fixed_amount'` supported; others → `calc_method_unsupported`.
- **`payroll_change_request.py`** — `submit_change_request`, `approve_change_request`, `reject_change_request`, `cancel_change_request`. Approver ≠ requester.
- **`payroll_pdf.py`** — `render_payslip_pdf(...)` pure stdlib, no reportlab.
- **`payroll_seed.py`** — `ensure_system_earning_types(db)` — 4 types, all `frequency='regular'`.
- **`payroll_import_fields.py`** — `IMPORT_FIELDS`, `validate_import_row_fields`, `apply_import_row_fields`. **Not wired into `import_employees.py` yet.**
- **`provisioning.py`** — `provision_tenant`, `_drop_tenant_database`, `_tenant_db_name`, `_admin_url`. Template fast path when `PAYROLL_TEST_TEMPLATE_DB=1`.
- **`payroll_audit.py`** — `write_audit(...)` filters by `AuditLog` columns.

### Test conventions
- `disposable_tenant` fixture **defined locally per module**.
- `_mk_user` must create real `User` rows (FK to `user.id`).
- `_mk_emp`, `_mk_earning_type`, `_mk_deduction_type` use unique codes.
- `payslip.revision` part of `uq_payslip_period_employee_rev`; multiple payslips for same (period, employee) need higher revisions.
- Endpoint permission matrix: `test_payroll_endpoint_permissions.py` over `EXPECTED_ROUTES`.
- Section-6 matrix: `tests/test_permissions.py`.
- `test_schema_drift.py` compares every non-control table's model columns to the tenant DB.
- Hand-worked payslips: drop a JSON into `tests/data/payslip_cases/` (copy `TEMPLATE.json`); `test_payslip_cases_framework.py` parametrizes over them. Skip is expected when no cases exist.

## 10. Decisions log
### 2A: A10 = new `ATTENDANCE_VIEW` (auditor excluded).
### 2B: B10 = leave approval triggers attendance recompute.
### 2C: C1 audit old/new snapshot; C2 adjusted days indistinguishable; C3 mark_reviewed refuses open exceptions; C9 sheet page 50/200, range 31d.
### Chapter 4 D1–D16
D1 statutory tables in control DB; D2 JSON format; D3 `contracted_weekly_hours` column; D4 hourly-rate formula pending accountant; D5 half-up per line; D6 preview persists; D7 reopen increments revision; D8 SDL tenant setting; D9 medical credits monthly×12; D10 11F from table only; D11 monthly only; D12 platform-admin typed confirm; D13 = E14; D14 net-pay floor 0.00; D15 regular-earnings only pending accountant; D16 bank/exports out of scope.
### Chapter 4 E1–E14
E1 control-DB tables, version by pay_date, rules snapshot; E2 eleven tables; E3 TaxEngine + `tax_method_unsupported`; E4 UIF ceiling-first + `sdl_applies` + `uif_exempt`; E5 credits only when members > 0; E6 `age_reference_date` + `missing_date_of_birth`; E7 floor deferral + `deduction_exceeds_floor_legal_order`; E8 six formulas + `formula_acks`; E9a-e reopen/finalise/preview rules; E10 templates + fake fixtures; E11 `pay_basis='monthly'`; E12 PDF renderer, storage deferred; E13 speed measurement; E14 own via SELF_VIEW, others via PAYSLIP_VIEW.
### Chapter 4 F1–F8
F1 PowerShell loader; F2 one template per type; F3 all writes route through 1C.10 change requests; F4 preview persists, purges prior, excluded from `/payslips`; F5 system earnings `frequency='regular'`, only genuine once-offs refused; F6 settings GET/PATCH; F7 garnishee never deferred; F8 measure and implement speed-up.

## 11. Chapter 4 close
### F4 preview persistence — implemented 016a
Preview writes one `payroll_run(kind='preview')` + payslips with `status='preview'`. Re-run purges prior. Excluded from `/payslips` and get/explain/pdf. Finalise purges previews.
### F3 change-request flow — 015a + 015b-1 + 015b-2
`POST /payroll/change-requests` (HR, PAY_RATE_REQUEST). `POST .../{id}/approve` (payroll_admin, PAY_RATE_APPROVE) writes target row in same transaction. `reject`, `cancel`. Approver ≠ requester. Pending has zero effect.
### F7 legal orders — 004a-iii-b
Non-garnishee exceeding floor → whole line deferred + balance carried. Garnishee exceeding floor → `deduction_exceeds_floor_legal_order`.
### E8 formula ack — 004a-i
`GET /payroll-formulas/readiness`, `POST /payroll-formulas/{code}/acknowledge`. `finalise()` refuses with `formula_unacknowledged` until all six acked.
### apply_bundle.py improvement — 016c
Now runs tests for importers of changed sources (capped at 20). `do_commit` skips gitignored files.
### Hand-worked framework — 016c
`tests/data/payslip_cases/TEMPLATE.json` + `test_payslip_cases_framework.py`. Add a JSON per case; no code changes.

## 12. Open items
- `reviewed_at` not cleared when only an exception appears (2C).
- Sheet 31-day limit vs 32-day daily endpoint (off-by-one).
- Leave reconciliation flags defined, wiring to leave approval pending.
- Production implementations of `StorageDep`, `JobRunnerDep`, `ScannerDep`.
- **`apply_import_row_fields` not wired into `import_employees.py`.**
- **`provision_tenant` does not auto-seed system earning types.**
- Payslip PDF returns bytes; `StorageDep` integration deferred.
- Hand-worked cases folder empty; needs cases from accountant.
- Bank file, journals, EMP201/EMP501/IRP5/IT3(a) — Chapter 5.
- Photo retention, HMAC on punch payloads, daily sweep scheduler.
- **`per_hour` earning types refused (`calc_method_unsupported`) until attendance integration (Chapter 5).**
- Reimbursements always empty (no source table).
- `formula_acks` JSON uses full reassignment (SQLAlchemy tracking).
- **Full suite is now 53 min (3205 s). At Chapter 5's growth rate it crosses an hour. Speed-up needs extending before Chapter 5 close.**

## 13. Waiting on user
- SARS: Rates of Normal Tax; Tax Rebates; Tax Thresholds; Medical Scheme Fees Tax Credit; Retirement Fund 11F; PAYE Guide for Employers (PAYE-GEN-01-G01); Tax Deduction Tables by frequency.
- Dept of Employment and Labour: UIF Earnings Ceiling.
- SDL: rate + annual exemption.
- Accountant: D4 hourly-rate; D15 PAYE for irregular pay; E6 age reference date; rounding rules per line vs cumulative; UIF ceiling-first; SDL `sdl_applies` semantics; salaried proration; leave + holiday pay rules; fringe benefits; opening YTD balances.
- Hand-computed payslip cases.
- Official public holiday dates per year.
- Bank file spec.
- POPIA + BCEA legal / consent wording.
- Device SDKs.

## 14. Next step
- Write **Chapter 5 SPEC** (bank file, journals, EMP201/EMP501/IRP5/IT3(a) exports, POPIA subject-access) as the first reply, per the working agreement: SPEC-only, no code, decide the ordering with the user.
- **Before Chapter 5 closes**, extend the suite speed-up. Options to weigh:
  - Session-scoped tenant with per-test savepoint rollback (biggest win, biggest risk)
  - Extend template fast path to the seed step (medium win)
  - Widen `--fast` marker set (medium win, no risk)
- Carry the F3 wiring for `import_employees.py` and the `provision_tenant` seed hook into Chapter 5's opening items.

## 15. UNCERTAIN / VERIFY FIRST
| Item | Verify with |
|---|---|
| Current test count | `cd backend; python -m pytest --collect-only -q \| Select-Object -Last 3` |
| Current full-suite time | `powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1` — baseline 3205 s at `9e20b35` |
| Last commit hash | `git log --oneline -3` — expect `9e20b35` at tip |
| Whether main is pushed | `git status` — expect clean, no "ahead of origin/main" |
| Whether 017 HANDOFF landed | `Test-Path docs/HANDOFF.md` — expect True |
| Whether Chapter 3 3A committed | `git log --oneline -- backend/app/db/tenant/models/leave.py` |
| Whether demo tenant exists | `psql -U postgres -d postgres -c "SELECT datname FROM pg_database WHERE datname LIKE 'tenant_%';"` |
| Whether 0020 applied to a tenant | per tenant: `SELECT version_num FROM alembic_version;` — expect `ten_0020` |
| Whether template fast path saves time | re-time `run_tests.ps1` vs 2435 s 2C baseline and 3205 s current |
| Whether `test_fastpath_diagnostic.py` passes under env | `cd backend; $env:PAYROLL_TEST_TEMPLATE_DB='1'; $env:PAYROLL_TEST_FAST_HASH='1'; python -m pytest tests/test_fastpath_diagnostic.py -q --no-header` |
| Full text of A1–A9, A11–A12, B1–B9, B11–B14, C4–C8, C10 | Claude's chapter specs / master brief |
| Whether apply_bundle.py retries tests for importers | read `tools/apply_bundle.py` `find_dependent_tests` |
| Whether provision_tenant calls ensure_system_earning_types | `Select-String -Path backend\app\services\provisioning.py -Pattern "ensure_system"` |

# END OF FILE
