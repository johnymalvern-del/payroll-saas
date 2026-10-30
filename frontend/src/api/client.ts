import createClient from "openapi-fetch";
import type { paths } from "./schema";

let accessToken: string | null = null;
let refreshPromise: Promise<boolean> | null = null;
let onUnauthorized: (() => void) | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function setOnUnauthorized(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

async function refreshOnce(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    try {
      const res = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) return false;
      const body = (await res.json().catch(() => null)) as
        | { access_token?: unknown }
        | null;
      const token = body?.access_token;
      if (typeof token === "string") {
        accessToken = token;
        return true;
      }
      return false;
    } catch {
      return false;
    }
  })();
  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

const wrappedFetch = async (req: Request): Promise<Response> => {
  const original = req.clone();
  const first = new Request(req);
  if (accessToken) first.headers.set("Authorization", `Bearer ${accessToken}`);
  let res = await fetch(first);
  if (res.status !== 401) return res;
  const ok = await refreshOnce();
  if (!ok) {
    onUnauthorized?.();
    return res;
  }
  const retry = new Request(original);
  if (accessToken) retry.headers.set("Authorization", `Bearer ${accessToken}`);
  res = await fetch(retry);
  if (res.status === 401) onUnauthorized?.();
  return res;
};

export const api = createClient<paths>({
  baseUrl: "/api/v1",
  credentials: "include",
  fetch: wrappedFetch,
});
