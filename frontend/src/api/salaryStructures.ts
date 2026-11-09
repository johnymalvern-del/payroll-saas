import { absoluteUrl, wrappedFetch } from "./client";

export type ComponentKind = "earning" | "deduction";
export type PayBasis = "hourly" | "daily" | "monthly";

export type StructureComponentIn = {
  kind: ComponentKind;
  earning_type_id: string | null;
  deduction_type_id: string | null;
  amount: string | null;
  rate: string | null;
};

export type StructureCreateIn = {
  name: string;
  description: string | null;
  pay_basis: PayBasis;
  base_rate: string;
  components: StructureComponentIn[];
};

export type StructureEditIn = {
  version_number: number;
  row_version: number;
  name?: string | null;
  description?: string | null;
  pay_basis?: PayBasis | null;
  base_rate?: string | null;
  components?: StructureComponentIn[] | null;
};

export type StructureComponentOut = {
  id: string;
  kind: string;
  earning_type_id: string | null;
  deduction_type_id: string | null;
  amount: string | null;
  rate: string | null;
};

export type StructureOut = {
  id: string;
  structure_group_id: string;
  version_number: number;
  is_current: boolean;
  name: string;
  description: string | null;
  pay_basis: string;
  base_rate: string;
  is_active: boolean;
  row_version: number;
  created_at: string;
  updated_at: string;
  components: StructureComponentOut[];
};

export type StructureListOut = {
  items: StructureOut[];
  next_cursor?: string | null;
};
export type DeactivateOut = { deactivated: boolean; structure_group_id: string };

export class StructureApiError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;
  constructor(code: string, status: number, details?: Record<string, unknown>) {
    super(code);
    this.name = "StructureApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

async function _handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as {
      error?: { code?: string; details?: Record<string, unknown> };
    };
    throw new StructureApiError(
      body.error?.code ?? `http_${res.status}`,
      res.status,
      body.error?.details,
    );
  }
  return (await res.json()) as T;
}

export async function createStructure(
  body: StructureCreateIn,
): Promise<StructureOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/payroll/salary-structures"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  return _handle<StructureOut>(res);
}

export async function listStructures(
  params?: { limit?: number; cursor?: string | null } | null,
): Promise<StructureListOut> {
  // Tolerate React Query calling this as `queryFn: listStructures` — the
  // QueryFunctionContext object has no limit/cursor fields, so both checks
  // fall through and the request is unpaginated (first page).
  const qs = new URLSearchParams();
  if (params && typeof params === "object") {
    const p = params as { limit?: unknown; cursor?: unknown };
    if (typeof p.limit === "number") qs.set("limit", String(p.limit));
    if (typeof p.cursor === "string" && p.cursor) qs.set("cursor", p.cursor);
  }
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(`/api/v1/payroll/salary-structures${suffix}`),
      { method: "GET", credentials: "include" },
    ),
  );
  return _handle<StructureListOut>(res);
}

export async function getCurrentStructure(groupId: string): Promise<StructureOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/salary-structures/${groupId}`), {
      method: "GET",
      credentials: "include",
    }),
  );
  return _handle<StructureOut>(res);
}

export async function listVersions(groupId: string): Promise<StructureListOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(`/api/v1/payroll/salary-structures/${groupId}/versions`),
      { method: "GET", credentials: "include" },
    ),
  );
  return _handle<StructureListOut>(res);
}

export async function getVersion(groupId: string, n: number): Promise<StructureOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(`/api/v1/payroll/salary-structures/${groupId}/versions/${n}`),
      { method: "GET", credentials: "include" },
    ),
  );
  return _handle<StructureOut>(res);
}

export async function editStructure(
  groupId: string, body: StructureEditIn,
): Promise<StructureOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/salary-structures/${groupId}`), {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  return _handle<StructureOut>(res);
}

export async function deactivateStructure(
  groupId: string,
): Promise<DeactivateOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(`/api/v1/payroll/salary-structures/${groupId}/deactivate`),
      { method: "POST", credentials: "include" },
    ),
  );
  return _handle<DeactivateOut>(res);
}

// END OF FILE