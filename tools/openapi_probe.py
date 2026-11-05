import json, sys

from app.main import app

schema = app.openapi()
want = ("/punches", "/devices", "/auth/me")
print("openapi_url:", app.openapi_url)
print("docs_url:", app.docs_url)
print("total paths:", len(schema["paths"]))
print("candidate paths matching:",
      [p for p in schema["paths"] if any(w in p for w in want)])
print()
for p in sorted(schema["paths"]):
    if not any(w in p for w in want):
        continue
    print("===== " + p + " =====")
    for meth, op in schema["paths"][p].items():
        if meth not in ("get", "post", "patch", "put", "delete"):
            continue
        print(meth.upper())
        rb = op.get("requestBody", {})
        if rb:
            print("  reqBody:", json.dumps(rb)[:3000])
        for code, resp in (op.get("responses") or {}).items():
            s = resp.get("content", {}).get("application/json", {}).get("schema", {})
            if s:
                print("  resp " + code + ":", json.dumps(s)[:500])