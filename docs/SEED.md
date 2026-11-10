# Demo seed (B-2)

Tenant slug **`tenant-demo`** (hyphen, not underscore -- the backend slug regex
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
```

## Exception backfill (design note)

`_backfill_exceptions` in `demo_seed.py` fabricates at most 2 open rows per
exception type for the demo tenant. This is deliberate: the real attendance
engine emits most types naturally during recompute (`missing_out`,
`low_confidence`, etc.), but a few depend on date-sensitive punch-vs-shift
alignment that can drift with the calendar. Backfilling guarantees the demo
tenant always shows all 10 exception types regardless of when the seed runs.

Types backfilled by the seed (`types_missing`):

- `missing_in`
- `no_shift_match`
- `low_confidence`
- `overtime_unapproved`
- `duplicate`
- `device_clock_gap`
- `employee_query`
- `absent_expected`
- `too_long`

`missing_out` is engine-generated (a punch exists but has no matching out-punch
-- see `attendance_engine.py:450`) and is **not** backfilled.

Tradeoff (accepted): a demo `no_shift_match` row is a fabricated example -- the
underlying demo data does not actually contain a punch with no matching shift.
For a real demo of that scenario, seed a punch for a day whose employee has no
shift. This is the same tradeoff already made for the other 8 backfilled types.

Duplicates are guarded by checking `(employee_id, work_date, type)` against
existing open rows; the partial unique index `uq_exception_item_open` forbids
overlapping open rows.

`no_shift_match` was added to this list in commit `c124636` -- before that,
`test_seed_exception_spread_covers_all_ten_real_types` was failing because
the seed only backfilled 8 of the 10 types. The failure was pre-existing
(never surfaced in earlier M3 gates because `test_seed_demo.py` was not in
the targeted subset) and exposed by the M3.5 full-backend run.
