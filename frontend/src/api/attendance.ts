import { wrappedFetch } from "./client";

export type SheetCell = {
  work_date: string;
  status: string | null;
  worked_minutes: number | null;
  normal_minutes: number | null;
  overtime_minutes: number | null;
  flags: string[];
  open_exception_count: number;
  locked: boolean;
  reviewed: boolean;
};

export type SheetEmployee = {
  employee_id: string;
  employee_code: string;
  employee_name: string;
  site_id: string | null;
  department_id: string | null;
  days: SheetCell[];
};

export type SheetOut = {
  items: SheetEmployee[];
  next_cursor: string | null;
  total?: number | null;
};

export type Ref = { id: string; name: string };

function warnShapeMismatch(data: unknown): void {
  if (!data || typeof data !== "object") {
    console.warn("[attendance] sheet response is not an object", data);
    return;
  }
  const obj = data as Record<string, unknown>;
  if (!Array.isArray(obj.items)) {
    console.warn("[attendance] sheet response missing items array", Object.keys(obj));
    return;
  }
  const emp = obj.items[0];
  if (!emp || typeof emp !== "object") return;
  const wantEmp = ["employee_id", "employee_code", "employee_name", "days"];
  const missEmp = wantEmp.filter((k) => !(k in (emp as Record<string, unknown>)));
  if (missEmp.length > 0) {
    console.warn(
      "[attendance] sheet employee missing keys:",
      missEmp,
      "got:",
      Object.keys(emp as Record<string, unknown>),
    );
  }
  const days = (emp as Record<string, unknown>).days;
  if (Array.isArray(days) && days.length > 0) {
    const c = days[0];
    if (c && typeof c === "object") {
      const wantCell = [
        "work_date",
        "status",
        "worked_minutes",
        "flags",
        "open_exception_count",
        "locked",
        "reviewed",
      ];
      const missCell = wantCell.filter((k) => !(k in (c as Record<string, unknown>)));
      if (missCell.length > 0) {
        console.warn(
          "[attendance] sheet cell missing keys:",
          missCell,
          "got:",
          Object.keys(c as Record<string, unknown>),
        );
      }
    }
  }
}

export async function fetchSheet(params: {
  fromDate: string;
  toDate: string;
  siteId?: string | null;
  branchId?: string | null;
  departmentId?: string | null;
  includeTerminated?: boolean;
  limit?: number;
  cursor?: string | null;
}): Promise<SheetOut> {
  const qs = new URLSearchParams();
  qs.set("from_date", params.fromDate);
  qs.set("to_date", params.toDate);
  if (params.siteId) qs.set("site_id", params.siteId);
  if (params.branchId) qs.set("branch_id", params.branchId);
  if (params.departmentId) qs.set("department_id", params.departmentId);
  if (params.includeTerminated) qs.set("include_terminated", "true");
  qs.set("limit", String(params.limit ?? 50));
  if (params.cursor) qs.set("cursor", params.cursor);
  const res = await wrappedFetch(
    new Request(`/api/v1/attendance/sheet?${qs.toString()}`, {
      credentials: "include",
    }),
  );
  if (!res.ok) {
    throw new Error(`sheet fetch failed: ${res.status}`);
  }
  const data = await res.json();
  warnShapeMismatch(data);
  return data as SheetOut;
}

async function fetchRefs(path: string): Promise<Ref[]> {
  const res = await wrappedFetch(
    new Request(`/api/v1${path}?limit=500`, { credentials: "include" }),
  );
  if (!res.ok) return [];
  const body = (await res.json()) as { items?: Ref[] };
  return body.items ?? [];
}

export function fetchBranches(): Promise<Ref[]> {
  return fetchRefs("/branches");
}

export function fetchSites(): Promise<Ref[]> {
  return fetchRefs("/sites");
}

export function fetchDepartments(): Promise<Ref[]> {
  return fetchRefs("/departments");
}
