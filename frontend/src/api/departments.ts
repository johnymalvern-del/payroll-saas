import { getAccessToken } from "./client";
import { getTenantSlug } from "./tenant";

const BASE = "/api/v1";

function authHeaders(json = true): Record<string, string> {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  const slug = getTenantSlug();
  if (slug) h["X-Tenant-Slug"] = slug;
  const tok = getAccessToken();
  if (tok) h["Authorization"] = `Bearer ${tok}`;
  return h;
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    credentials: "include",
    headers: authHeaders(body !== undefined),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      (err as { error?: { message?: string } })?.error?.message ??
        `HTTP ${res.status}`,
    );
  }
  return (await res.json()) as T;
}

export type Department = {
  id: string;
  name: string;
  code: string;
  parent_id: string | null;
  is_active: boolean;
  row_version: number;
};

export type DepartmentCreateIn = { name: string; code: string; parent_id?: string | null };
export type DepartmentPatchIn = Partial<DepartmentCreateIn> & { row_version: number; is_active?: boolean };
export type DepartmentListOut = { items: Department[]; next_cursor?: string | null; total?: number | null };

export const departmentsApi = {
  list: () => req<DepartmentListOut>("GET", "/departments"),
  create: (b: DepartmentCreateIn) => req<Department>("POST", "/departments", b),
  patch: (id: string, b: DepartmentPatchIn) => req<Department>("PATCH", `/departments/${id}`, b),
  remove: (id: string) => req<void>("DELETE", `/departments/${id}`),
};
