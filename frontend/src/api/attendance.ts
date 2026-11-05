import { absoluteUrl, wrappedFetch } from "./client";

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

export type Punch = {
  id: string;
  punch_time: string;
  direction: string;
  source: string;
  confidence: number | null;
};

export type ExceptionRow = {
  id: string;
  type: string;
  message: string;
  status: string;
};

export type DayOut = {
  employee_id: string;
  employee_code: string;
  employee_name: string;
  work_date: string;
  status: string | null;
  first_in: string | null;
  last_out: string | null;
  worked_minutes: number | null;
  normal_minutes: number | null;
  overtime_minutes: number | null;
  flags: string[];
  open_exception_count: number;
  locked: boolean;
  reviewed: boolean;
  punches: Punch[];
  exceptions: ExceptionRow[];
  segments: SegmentOut[];
  shift_id: string | null;
};

export type SegmentOut = {
  id: string;
  attendance_day_id: string;
  local_date: string;
  day_type: string;
  kind: string;
  tier: number;
  minutes: number;
  rate_method: string;
  rate_value: string;
  overtime_status: string | null;
  source_refs: unknown[];
};

export type DailyRow = {
  employee_id: string;
  employee_code: string;
  employee_name: string;
  work_date: string;
  status: string | null;
  first_in: string | null;
  last_out: string | null;
  worked_minutes: number | null;
  normal_minutes: number | null;
  overtime_minutes: number | null;
  flags: string[];
  open_exception_count: number;
  locked: boolean;
  reviewed: boolean;
};

export type DailyOut = {
  items: DailyRow[];
  next_cursor: string | null;
  total?: number | null;
};

export type MarkReviewedRequest = {
  fromDate: string;
  toDate: string;
  siteId?: string | null;
  branchId?: string | null;
  departmentId?: string | null;
  includeTerminated?: boolean;
};

export type RefusedDay = {
  employee_id: string;
  employee_name?: string;
  work_date: string;
  reason: string;
};

export type MarkReviewedOut = {
  reviewed_count: number;
  refused_days: RefusedDay[];
};

function warn(where: string, data: unknown, want: string[]): void {
  if (!data || typeof data !== "object") {
    console.warn(`[attendance] ${where}: not an object`, data);
    return;
  }
  const miss = want.filter((k) => !(k in (data as Record<string, unknown>)));
  if (miss.length > 0) {
    console.warn(`[attendance] ${where} missing keys:`, miss, "got:",
      Object.keys(data as Record<string, unknown>));
  }
}

function normaliseSheetOut(data: unknown): SheetOut {
  const obj = (data ?? {}) as Record<string, unknown>;
  return {
    items: Array.isArray(obj.items) ? (obj.items as SheetEmployee[]) : [],
    next_cursor: typeof obj.next_cursor === "string" ? obj.next_cursor : null,
    total: typeof obj.total === "number" ? obj.total : null,
  };
}

function normaliseDailyOut(data: unknown): DailyOut {
  const obj = (data ?? {}) as Record<string, unknown>;
  return {
    items: Array.isArray(obj.items) ? (obj.items as DailyRow[]) : [],
    next_cursor: typeof obj.next_cursor === "string" ? obj.next_cursor : null,
    total: typeof obj.total === "number" ? obj.total : null,
  };
}

function normaliseDayOut(data: unknown): DayOut {
  const obj = (data ?? {}) as Record<string, unknown>;
  return {
    employee_id: String(obj.employee_id ?? ""),
    employee_code: String(obj.employee_code ?? ""),
    employee_name: String(obj.employee_name ?? ""),
    work_date: String(obj.work_date ?? ""),
    status: typeof obj.status === "string" ? obj.status : null,
    first_in: typeof obj.first_in === "string" ? obj.first_in : null,
    last_out: typeof obj.last_out === "string" ? obj.last_out : null,
    worked_minutes: typeof obj.worked_minutes === "number" ? obj.worked_minutes : null,
    normal_minutes: typeof obj.normal_minutes === "number" ? obj.normal_minutes : null,
    overtime_minutes: typeof obj.overtime_minutes === "number" ? obj.overtime_minutes : null,
    flags: Array.isArray(obj.flags) ? (obj.flags as string[]) : [],
    open_exception_count:
      typeof obj.open_exception_count === "number" ? obj.open_exception_count : 0,
    locked: obj.locked === true,
    reviewed: obj.reviewed === true,
    punches: Array.isArray(obj.punches) ? (obj.punches as Punch[]) : [],
    exceptions: Array.isArray(obj.exceptions) ? (obj.exceptions as ExceptionRow[]) : [],
    segments: Array.isArray(obj.segments) ? (obj.segments as SegmentOut[]) : [],
    shift_id: typeof obj.shift_id === "string" ? obj.shift_id : null,
  };
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
    new Request(absoluteUrl(`/api/v1/attendance/sheet?${qs.toString()}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) {
    throw new Error(`sheet fetch failed: ${res.status}`);
  }
  const data = await res.json();
  warn("sheet response", data, ["items"]);
  return normaliseSheetOut(data);
}

export async function fetchDaily(params: {
  date: string;
  siteId?: string | null;
  branchId?: string | null;
  departmentId?: string | null;
  includeTerminated?: boolean;
  limit?: number;
  cursor?: string | null;
}): Promise<DailyOut> {
  const qs = new URLSearchParams();
  qs.set("date", params.date);
  if (params.siteId) qs.set("site_id", params.siteId);
  if (params.branchId) qs.set("branch_id", params.branchId);
  if (params.departmentId) qs.set("department_id", params.departmentId);
  if (params.includeTerminated) qs.set("include_terminated", "true");
  qs.set("limit", String(params.limit ?? 50));
  if (params.cursor) qs.set("cursor", params.cursor);
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/attendance/daily?${qs.toString()}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) {
    throw new Error(`daily fetch failed: ${res.status}`);
  }
  const data = await res.json();
  warn("daily response", data, ["items"]);
  return normaliseDailyOut(data);
}

export async function fetchEmployeeById(
  id: string,
): Promise<{
  id: string;
  first_name: string;
  last_name: string;
  employee_code: string;
} | null> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/employees/${id}`), { credentials: "include" }),
  );
  if (!res.ok) return null;
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null;
  if (!data) return null;
  return {
    id: String(data.id ?? ""),
    first_name: String(data.first_name ?? ""),
    last_name: String(data.last_name ?? ""),
    employee_code: String(data.employee_code ?? ""),
  };
}

export async function fetchExceptionsForDay(
  employeeId: string,
  workDate: string,
): Promise<ExceptionRow[]> {
  const qs = new URLSearchParams();
  qs.set("employee_id", employeeId);
  qs.set("from_date", workDate);
  qs.set("to_date", workDate);
  qs.set("limit", "100");
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/attendance/exceptions?${qs.toString()}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) return [];
  const data = (await res.json().catch(() => null)) as { items?: unknown } | null;
  return Array.isArray(data?.items) ? (data!.items as ExceptionRow[]) : [];
}

export async function fetchDay(employeeId: string, workDate: string): Promise<DayOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(`/api/v1/attendance/day/${employeeId}/${workDate}`),
      { credentials: "include" },
    ),
  );
  if (!res.ok) {
    throw new Error(`day fetch failed: ${res.status}`);
  }
  const data = await res.json();
  warn("day response", data, ["employee_id", "work_date", "punches"]);
  return normaliseDayOut(data);
}

export async function markReviewed(req: MarkReviewedRequest): Promise<MarkReviewedOut> {
  const body: Record<string, unknown> = {
    from_date: req.fromDate,
    to_date: req.toDate,
  };
  if (req.siteId) body.site_id = req.siteId;
  if (req.branchId) body.branch_id = req.branchId;
  if (req.departmentId) body.department_id = req.departmentId;
  if (req.includeTerminated) body.include_terminated = true;
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/attendance/mark_reviewed"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  if (!res.ok) {
    throw new Error(`mark reviewed failed: ${res.status}`);
  }
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  const refused = Array.isArray(data.refused_days)
    ? (data.refused_days as RefusedDay[])
    : [];
  const count =
    typeof data.reviewed_count === "number" ? data.reviewed_count : 0;
  return { reviewed_count: count, refused_days: refused };
}

async function fetchRefs(path: string): Promise<Ref[]> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1${path}?limit=500`), {
      credentials: "include",
    }),
  );
  if (!res.ok) return [];
  const body = (await res.json().catch(() => ({}))) as { items?: unknown };
  return Array.isArray(body.items) ? (body.items as Ref[]) : [];
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
