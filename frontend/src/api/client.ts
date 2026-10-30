import createClient from "openapi-fetch";
import type { paths } from "./schema";
import { getTenantSlug } from "./tenant";

export type TokenStore = {
  getToken: () => string | null;
  setToken: (token: string | null) => void;
};

export type RefreshFn = () => Promise<string | null>;

export function createWrappedFetch(
  tokenStore: TokenStore,
  refresh: RefreshFn,
  onUnauthorized: () => void,
): (req: Request) => Promise<Response> {
  return async (req) => {
    const original = req.clone();
    const first = new Request(req);
    const slug = getTenantSlug();
    if (slug) first.headers.set("X-Tenant-Slug", slug);
    const token = tokenStore.getToken();
    if (token) first.headers.set("Authorization", `Bearer ${token}`);
    let res = await fetch(first);
    if (res.status !== 401) return res;

    const newToken = await refresh();
    if (!newToken) {
      onUnauthorized();
      return res;
    }
    tokenStore.setToken(newToken);

    const retry = new Request(original);
    if (slug) retry.headers.set("X-Tenant-Slug", slug);
    retry.headers.set("Authorization", `Bearer ${newToken}`);
    res = await fetch(retry);
    if (res.status === 401) onUnauthorized();
    return res;
  };
}

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

let refreshPromise: Promise<string | null> | null = null;

export async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    try {
      const slug = getTenantSlug();
      const res = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "include",
        headers: slug ? { "X-Tenant-Slug": slug } : {},
      });
      if (!res.ok) return null;
      const body = (await res.json().catch(() => null)) as
        | { access_token?: unknown }
        | null;
      return typeof body?.access_token === "string" ? body.access_token : null;
    } catch {
      return null;
    }
  })();
  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

let onUnauthorizedDefault: (() => void) | null = null;

export function setOnUnauthorized(fn: (() => void) | null): void {
  onUnauthorizedDefault = fn;
}

export const wrappedFetch = createWrappedFetch(
  { getToken: getAccessToken, setToken: setAccessToken },
  refreshAccessToken,
  () => onUnauthorizedDefault?.(),
);

export const api = createClient<paths>({
  baseUrl: "/api/v1",
  credentials: "include",
  fetch: wrappedFetch,
});
