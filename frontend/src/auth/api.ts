import { parseApiError, type ApiError } from "../api/errors";
import { getTenantSlug } from "../api/tenant";

const BASE = "/api/v1";

function tenantHeaders(): Record<string, string> {
  const slug = getTenantSlug();
  return slug ? { "X-Tenant-Slug": slug } : {};
}

export type LoginResult = {
  accessToken: string;
  mustChangePassword: boolean;
};

export class AuthRequestError extends Error {
  readonly apiError: ApiError;
  constructor(err: ApiError) {
    super(err.message);
    this.apiError = err;
  }
}

export async function loginRequest(
  identifier: string,
  password: string,
): Promise<LoginResult> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...tenantHeaders() },
    body: JSON.stringify({ identifier, password }),
  });
  if (!res.ok) {
    throw new AuthRequestError(await parseApiError(res));
  }
  const body = (await res.json().catch(() => null)) as
    | { access_token?: unknown; must_change_password?: unknown }
    | null;
  const token = body?.access_token;
  if (typeof token !== "string") {
    throw new AuthRequestError({
      code: "bad_response",
      message: "Login response missing access_token",
      status: 200,
    });
  }
  return {
    accessToken: token,
    mustChangePassword: body?.must_change_password === true,
  };
}

export async function logoutRequest(): Promise<void> {
  try {
    await fetch(`${BASE}/auth/logout`, {
      method: "POST",
      credentials: "include",
      headers: tenantHeaders(),
    });
  } catch {
    // network error on logout is not fatal; local state clears regardless
  }
}

export async function changePasswordRequest(params: {
  currentPassword: string;
  newPassword: string;
}): Promise<void> {
  const res = await fetch(`${BASE}/auth/change-password`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...tenantHeaders() },
    body: JSON.stringify({
      current_password: params.currentPassword,
      new_password: params.newPassword,
    }),
  });
  if (!res.ok) {
    throw new AuthRequestError(await parseApiError(res));
  }
}
