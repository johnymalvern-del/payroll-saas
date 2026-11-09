# Demo seed (B-2)

Tenant slug **`tenant-demo`** (hyphen, not underscore — the backend slug regex
is `^[a-z0-9][a-z0-9-]{1,60}$` and rejects underscores). `tenant-demo` is the
provisioned tenant used for local demos and manual testing.

## Run

```powershell
# default (--keep): do nothing if tenant-demo exists
.\scripts\seed_demo.ps1

# drop and recreate
.\scripts\seed_demo.ps1 --reset

# explicit --keep (same as default)
.\scripts\seed_demo.ps1 --keep
## F-10 M3.5 UI completion (committed)

Five M3-gap items delivered per `MILESTONE 3.5` spec. Each landed as its own
commit with its own gate:

| Item | Commit | Gate |
|---|---|---|
| Approve/reject/cancel on EmployeePayrollPage | `3aaa241` | 17/17 |
| Component editing in structure edit modal | `51bd5f1` | 16/16 |
| Cursor pagination for salary structures | `b2170a3` | 6 backend + 30 frontend |
| Filter assignment-linked CRs from queue | `fa09fee` | 11/11 |
| Demo seed backfills `no_shift_match` | `c124636` | 14/14 |

### Item 1 — approve/reject/cancel on EmployeePayrollPage (`3aaa241`)

Assignment history table gains a per-row Actions column when
`status = 'pending'`:

- **Approve** — `window.confirm` then `POST /employee-salary-assignments/{id}/approve`.
  Loading state via shared mutation `busyId` computed from
  `action.variables?.id`. Success invalidates
  `["employee_assignments", employeeId]`.
- **Reject** — modal with required `note` Textarea. Submit disabled until
  trimmed note is non-empty. `POST .../reject` with `{note}`.
- **Cancel** — `window.confirm` then `POST .../cancel`. Backend
  enforces requester-only via `not_requester` 403 (surfaced verbatim).

Errors mapped via extended `mapAssignmentError` (adds
`self_approval_forbidden`, `not_requester`, `not_pending`,
`assignment_effective_date_not_after_latest_approved`,
`assignment_state_conflict`, `approval_batch_failed`,
`approval_unexpected_error`, `close_set_mismatch`, `record_changed`).
Page-level dismissible Alert `assignment-action-error`.

Testids: `assignment-approve-{id}`, `assignment-reject-{id}`,
`assignment-cancel-{id}`, `assignment-reject-note`,
`assignment-reject-submit`, `assignment-reject-modal-cancel`,
`assignment-action-error`.

8 new tests; file total 17.

### Item 2 — component editing in structure edit modal (`51bd5f1`)

Edit modal gains a **Modify components** toggle (`toggle-components`).
Opening reveals a components editor seeded from the current version. Add,
remove, and edit are supported via the same draft-and-validate pattern
already used in the create modal (`SalaryStructuresPage`).

`componentsDirty` flag tracks any change. On submit, `components` is sent
**only** when dirty; otherwise the backend copies components as before. This
preserves the "rename only" fast path and satisfies "never silently modify
historical versions" — the backend already creates a new version on every
edit, and historical versions and their components are frozen.

Validation reuses create-modal rules: earning requires exactly one of
`amount`/`rate` and a type; deduction requires `amount` and a type and
forbids `rate`.

Testids: `toggle-components`, `edit-components-editor`,
`edit-component-row-{i}`, `edit-component-type-{i}`,
`edit-component-amount-{i}`, `edit-component-rate-{i}`,
`edit-component-remove-{i}`, `edit-add-earning`, `edit-add-deduction`.

6 new tests; file total 16.

### Item 3 — cursor pagination for salary structures (`b2170a3`)

**Backend additive change** (no schema, no migration): new
`list_current_structures_paginated(db, *, limit=100, cursor=None) ->
(list, next_cursor)` in `salary_structure_service.py`. The unpaginated
`list_current_structures(db)` is untouched so Stage B callers (including
`test_list_current_structures`) keep working. Ordering switched from
`name.asc()` to `id.asc()` for cursor stability. Opaque base64url cursor
`{"i": "<uuid>"}` mirrors the pattern in `payroll_change_requests.py`.

Endpoint `GET /payroll/salary-structures` gains optional `limit` / `cursor`
query params; response is a local `_StructureListPage` defined inside the
endpoint file so the shared `StructureListOut` schema (used by `/versions`)
is untouched. `limit` default 100, ceiling 500.

**Frontend:** `SalaryStructuresPage` switches from `useQuery` to
`useInfiniteQuery` with "Load more" (`structures-load-more`).
`isFetchNextPageError` surfaces a dedicated `structures-load-more-error`
alert so a failed subsequent page is not silently swallowed (TanStack Query
v5 keeps the query in `isSuccess` state after a next-page failure).
`listStructures(params?)` tolerates an unknown first-arg shape so
`EmployeePayrollPage`'s `queryFn: listStructures` continues to work
unchanged.

6 new backend tests in `test_salary_structure_pagination.py`; 3 new frontend
tests (file total 13).

### Item 4 — filter assignment-linked CRs from queue (`fa09fee`)

`ChangeRequestOut` (frontend type in `api/changeRequests.ts`) gains
`assignment_id: string | null` (backend has always sent it since M3 Stage C,
`269de14`).

`ChangeRequestsPage` filters `r.assignment_id != null` **after**
`flatMap`-flattening — the raw cursor walks all pages, then the filter runs
on the display set. Server cursor semantics preserved. Loosely null-checked
so pre-Stage-C records (hypothetically missing the field) still render.
Nothing deleted or hidden at API level: assignment-linked rows remain
accessible via `GET /payroll/change-requests/{id}` and via the salary
assignment detail page.

2 new tests (filtered-by-default; load-more preserves filter across pages);
file total 11.

### Item 5 — demo seed backfills `no_shift_match` (`c124636`)

Pre-existing test gap exposed by the M3.5 full-backend gate:
`test_seed_exception_spread_covers_all_ten_real_types` expected 10
exception types but the seed only backfilled 8. `no_shift_match` is emitted
by the engine only when a punch lands on a day with no matching shift
(`attendance_engine.py:847-848, 863, 993-996`) — the demo tenant's shifts
and punch dates align, so the branch never fires. The failure was
pre-existing, not M3.5-caused; never surfaced in earlier gates because
`test_seed_demo.py` was never in the targeted subset.

Fix: added `"no_shift_match"` to `types_missing` in
`_backfill_exceptions`. Same fabrication-vs-engine design tradeoff as the
existing 8 backfilled types — documented in `docs/SEED.md`. Duplicates
guarded by the pre-existing `existing`-set check against
`uq_exception_item_open`.

14/14 in `test_seed_demo.py` (was 13/14).

### Aggregate M3.5 test totals

- **Backend:** 6 new tests (item 3 pagination) + 1 pre-existing test fixed
  (item 5 seed). Full-backend baseline at M3 close (M3.5 §6 first full run):
  1300 passed / 1 failed / 4 skipped. After item 5 fix: **expected 1301
  passed / 4 skipped** on the next full run.
- **Frontend:** 19 new tests across items 1–4 (8 + 6 + 3 + 2). Full frontend
  suite at M3.5 gate: **193/193 passed** across 30 test files (verified in
  the `fa09fee` gate run; unchanged since — item 5 is backend-only).
- **Item 3 backend cross-check:** 127/127 green on the item-3 gate
  (`test_salary_structure_pagination.py` + `test_salary_structure_service.py`
  + `test_salary_structure_models.py` + `test_payroll_endpoint_permissions.py`).

### Known limitations

- **Approve/reject/cancel controls shown to all viewers of a pending row.**
  Cannot determine `current_user == submitter` without an extra `/me` fetch
  on this page. Backend `not_requester` 403 is authoritative and surfaced
  verbatim. Matches how `ChangeRequestsPage` handles the same problem.
- **Cancel from a non-requester 403s at action time**, not at button
  visibility. Same tradeoff as above.
- **Component editing toggle requires opt-in** — the common edit path
  (name / rate) never sends components, avoiding accidental component
  rewrites. Users editing components pay one extra click.
- **Pagination ordering changed** from name-alphabetical to id-ordered.
  Cosmetic; no UX test depends on structure ordering. Deliberate consequence
  of stable cursor keys.
- **Assignment-linked CRs are silently absent from the standalone queue.**
  Users who need to see them must open the assignment detail page. Backend
  guard already refuses individual actions on these children (since M3
  Stage C).
- **Seed fabricates `no_shift_match`** rather than producing it via the
  engine. Same tradeoff as the other 8 backfilled types.