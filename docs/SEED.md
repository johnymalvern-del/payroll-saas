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