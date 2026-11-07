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
  listDecisions: (params?: {
    workflow?: string;
    employee_id?: string;
    status?: string;
    limit?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.workflow) qs.set("workflow", params.workflow);
    if (params?.employee_id) qs.set("employee_id", params.employee_id);
    if (params?.status) qs.set("status", params.status);
    if (params?.limit) qs.set("limit", String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return req<DecisionListOut>("GET", `/decisions${suffix}`);
  },
  getDecision: (id: string) =>
    req<DecisionDetail>("GET", `/decisions/${id}`),
  verifyDecisionSnapshot: (id: string) =>
    req<{ valid: boolean; decision_id: string }>(
      "GET",
      `/decisions/${id}/verify`,
    ),
};

// ---- Phase 1B — decision records (read-only) ----

export type DecisionSummary = {
  id: string;
  employee_id: string;
  workflow: string;
  source_type: string;
  source_id: string | null;
  decision_type: string;
  initiator_type: string;
  initiator_user_id: string | null;
  company_default_mode: string | null;
  effective_workflow_mode: string | null;
  workflow_override_mode: string | null;
  execution_status: string;
  created_at: string;
};

export type DecisionSnapshot = {
  id: string;
  decision_id: string;
  created_at: string;
  schema_version: number;
  payload: Record<string, unknown>;
  sha256_hex: string;
};

export type DecisionDetail = DecisionSummary & {
  policy_version: string | null;
  statutory_version: string | null;
  recommendation: Record<string, unknown> | null;
  explanation: string | null;
  audit_id: string | null;
  evidence_snapshot_id: string | null;
  snapshot: DecisionSnapshot | null;
};

export type DecisionListOut = {
  items: DecisionSummary[];
  next_cursor: string | null;
  total: number | null;
};

