import { getAccessToken } from "./client";
import { getTenantSlug } from "./tenant";

const BASE = "/api/v1/intelligence";

export type IntelligenceSettings = {
  id: string;
  default_mode: "traditional" | "assisted" | "autonomous";
  acknowledged_at: string | null;
  acknowledged_by_user_id: string | null;
  row_version: number;
};

export type WorkflowMode = {
  workflow: string;
  company_default: string;
  override_mode: string | null;
  override_active: boolean;
  effective_mode: string;
  row_version: number | null;
  effective_from: string | null;
  autonomous_capability_implemented: boolean;
};

export type ModeChangeLog = {
  id: string;
  changed_by_user_id: string | null;
  changed_at: string;
  workflow: string | null;
  previous_mode: string;
  new_mode: string;
  reason: string;
  effective_from: string;
  audit_id: string | null;
};

function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
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
    headers: headers(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg =
      (err as { error?: { message?: string } })?.error?.message ??
      `HTTP ${res.status}`;
    const e = new Error(msg) as Error & { code?: string; status?: number };
    e.code = (err as { error?: { code?: string } })?.error?.code;
    e.status = res.status;
    throw e;
  }
  return (await res.json()) as T;
}

export const intelligenceApi = {
  getSettings: () => req<IntelligenceSettings>("GET", "/settings"),
  updateDefaultMode: (body: {
    default_mode: string;
    row_version: number;
    reason: string;
    acknowledged_autonomous?: boolean;
  }) => req<IntelligenceSettings>("PATCH", "/settings/default-mode", body),
  getWorkflowModes: () =>
    req<{ items: WorkflowMode[] }>("GET", "/settings/workflows"),
  updateWorkflowMode: (
    workflow: string,
    body: {
      mode: string;
      is_active: boolean;
      row_version: number | null;
      reason: string;
      acknowledged_autonomous?: boolean;
    },
  ) => req<WorkflowMode>("PATCH", `/settings/workflows/${workflow}`, body),
  getChangeLog: () =>
    req<{ items: ModeChangeLog[] }>("GET", "/settings/change-log?limit=50"),
};
