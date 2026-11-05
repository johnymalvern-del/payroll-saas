import json
from app.main import app

s = app.openapi()


def show(path, meth):
    op = s["paths"].get(path, {}).get(meth, {})
    ps = op.get("parameters", [])
    print(f"=== {meth.upper()} {path} ===")
    if not ps:
        print("  (no parameters)")
        return
    for p in ps:
        print(
            f"  {p['in']:8} {p['name']:22} "
            f"required={p.get('required', False)}  "
            f"schema={json.dumps(p.get('schema', {}))[:120]}"
        )


for path, meth in [
    ("/api/v1/employees", "get"),
    ("/api/v1/punches", "post"),
    ("/api/v1/punches", "get"),
    ("/api/v1/punches/batch", "post"),
]:
    show(path, meth)
    print()

print("=== all paths mentioning 'employee' ===")
for p in sorted(s["paths"]):
    if "employee" in p.lower():
        print(" ", p)