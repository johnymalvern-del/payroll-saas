"""Fix changePasswordRequest: attach Authorization: Bearer.
Also adds currentPassword to the params type (body already reads it).

Files touched: only frontend/src/auth/api.ts. LoginRequest and logoutRequest
are left unchanged (login must not send a token).
"""
import re
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "frontend" / "src" / "auth" / "api.ts"
src = P.read_text(encoding="utf-8")

# ---- 1. Add getAccessToken import if absent ----
if 'from "../api/client"' in src:
    print("api.ts: client import already present")
else:
    anchor = 'import { getTenantSlug } from "../api/tenant";'
    if anchor not in src:
        raise SystemExit("FATAL: tenant import anchor missing")
    src = src.replace(
        anchor,
        anchor + '\nimport { getAccessToken } from "../api/client";',
        1,
    )
    print("api.ts: added getAccessToken import")

# ---- 2. Replace changePasswordRequest wholesale ----
pat = re.compile(
    r"export async function changePasswordRequest\(params: \{[^}]*\}\): "
    r"Promise<void> \{.*?\n\}\s*$",
    re.S,
)
m = pat.search(src)
if not m:
    raise SystemExit("FATAL: changePasswordRequest not found at file tail")

new_fn = '''export async function changePasswordRequest(params: {
  currentPassword: string;
  newPassword: string;
}): Promise<void> {
  const token = getAccessToken();
  const res = await fetch(`${BASE}/auth/change-password`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...tenantHeaders(),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      current_password: params.currentPassword,
      new_password: params.newPassword,
    }),
  });
  if (!res.ok) {
    throw new AuthRequestError(await parseApiError(res));
  }
}
'''
src = src[:m.start()] + new_fn
P.write_text(src, encoding="utf-8")
print("api.ts: changePasswordRequest rewritten (sends Authorization)")