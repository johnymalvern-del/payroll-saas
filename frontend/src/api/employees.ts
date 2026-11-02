import { absoluteUrl, wrappedFetch } from "./client";

export type EmployeeStatus = "active" | "on_leave" | "suspended" | "terminated";
export type EmployeeType = "hourly" | "salaried" | "casual" | "contract";
export type PayBasis = "hourly" | "daily" | "monthly";
export type PayFrequency = "weekly" | "fortnightly" | "monthly";

/** Lightweight reference used by dropdowns elsewhere (exceptions/adjustments). */
export type EmployeeRef = {
  id: string;
  employee_code: string;
  first_name: string;
  last_name: string;
};

/** Full row from GET /api/v1/employees (EmployeeOut). */
export type EmployeeOut = {
  id: string;
  employee_code: string;
  first_name: string;
  last_name: string;
  national_id_masked: string | null;
  email: string | null;
  mobile: string | null;
  date_of_birth: string | null;
  hire_date: string;
  termination_date: string | null;
  status: string;
  job_title: string | null;
  branch_id: string | null;
  site_id: string | null;
  department_id: string | null;
  manager_id: string | null;
  employee_type: string;
  pay_basis: string;
  pay_frequency: string;
  base_rate: string | null;
  overtime_eligible: boolean;
  clocks: boolean;
  work_pattern_id: string | null;
  default_shift_id: string | null;
  bank_name: string | null;
  bank_account_number_masked: string | null;
  bank_branch_code: string | null;
  account_type: string | null;
  tax_number: string | null;
  medical_aid_dependants: number;
  retirement_fund_flags: string | null;
  uif_exempt: boolean;
  notes: string | null;
  row_version: number;
  site_timezone?: string | null;
};

export type EmployeeListResponse = {
  items: EmployeeOut[];
  next_cursor: string | null;
  total?: number | null;
};

export type EmployeeCreateIn = {
  employee_code: string;
  first_name: string;
  last_name: string;
  national_id?: string | null;
  email?: string | null;
  mobile?: string | null;
  date_of_birth?: string | null;
  hire_date: string;
  termination_date?: string | null;
  status?: string;
  job_title?: string | null;
  branch_id?: string | null;
  site_id?: string | null;
  department_id?: string | null;
  manager_id?: string | null;
  employee_type?: string;
  pay_basis?: string;
  pay_frequency?: string;
  base_rate?: number | string | null;
  overtime_eligible?: boolean;
  clocks?: boolean;
  work_pattern_id?: string | null;
  default_shift_id?: string | null;
  bank_name?: string | null;
  bank_account_number?: string | null;
  bank_branch_code?: string | null;
  account_type?: string | null;
  tax_number?: string | null;
  medical_aid_dependants?: number;
  retirement_fund_flags?: string | null;
  uif_exempt?: boolean;
  notes?: string | null;
};

/** PATCH forbids national_id, bank_account_number, base_rate on the backend. */
export type EmployeePatchIn = {
  row_version: number;
  employee_code?: string;
  first_name?: string;
  last_name?: string;
  email?: string | null;
  mobile?: string | null;
  date_of_birth?: string | null;
  hire_date?: string;
  termination_date?: string | null;
  status?: string;
  job_title?: string | null;
  branch_id?: string | null;
  site_id?: string | null;
  department_id?: string | null;
  manager_id?: string | null;
  employee_type?: string;
  pay_basis?: string;
  pay_frequency?: string;
  overtime_eligible?: boolean;
  clocks?: boolean;
  work_pattern_id?: string | null;
  default_shift_id?: string | null;
  bank_name?: string | null;
  bank_branch_code?: string | null;
  account_type?: string | null;
  tax_number?: string | null;
  medical_aid_dependants?: number;
  retirement_fund_flags?: string | null;
  uif_exempt?: boolean;
  notes?: string | null;
};

export class EmployeesApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, status: number) {
    super(code);
    this.name = "EmployeesApiError";
    this.code = code;
    this.status = status;
  }
}

const PAGE_LIMIT = 500;
const MAX_PAGES = 20;

/** Dropdown reference list — follows next_cursor (used by exceptions/adjustments). */
export async function fetchEmployees(): Promise<EmployeeRef[]> {
  const all: EmployeeRef[] = [];
  let cursor: string | null = null;
  let pages = 0;
  for (;;) {
    if (pages >= MAX_PAGES) {
      console.warn(`fetchEmployees: stopped at MAX_PAGES=${MAX_PAGES}`);
      break;
    }
    const qs = new URLSearchParams();
    qs.set("limit", String(PAGE_LIMIT));
    if (cursor) qs.set("cursor", cursor);
    const res = await wrappedFetch(
      new Request(absoluteUrl(`/api/v1/employees?${qs.toString()}`), {
        credentials: "include",
      }),
    );
    if (!res.ok) {
      throw new Error(`http_${res.status}`);
    }
    const body = (await res.json().catch(() => ({}))) as {
      items?: unknown;
      next_cursor?: unknown;
    };
    if (Array.isArray(body.items)) all.push(...(body.items as EmployeeRef[]));
    cursor = typeof body.next_cursor === "string" ? body.next_cursor : null;
    pages += 1;
    if (!cursor) break;
  }
  return all;
}

export async function fetchEmployeesPage(params: {
  cursor?: string | null;
  limit?: number;
  include_terminated?: boolean;
  employee_code?: string;
  last_name?: string;
  status?: string;
}): Promise<EmployeeListResponse> {
  const qs = new URLSearchParams();
  qs.set("limit", String(params.limit ?? 100));
  if (params.cursor) qs.set("cursor", params.cursor);
  if (params.include_terminated) qs.set("include_terminated", "true");
  if (params.employee_code) qs.set("employee_code", params.employee_code);
  if (params.last_name) qs.set("last_name", params.last_name);
  if (params.status) qs.set("status", params.status);
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/employees?${qs.toString()}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw new Error(`http_${res.status}`);
  const body = (await res.json()) as EmployeeListResponse;
  return {
    items: body.items ?? [],
    next_cursor: body.next_cursor ?? null,
    total: body.total ?? null,
  };
}

export async function fetchEmployee(employeeId: string): Promise<EmployeeOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/employees/${employeeId}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw new Error(`http_${res.status}`);
  return (await res.json()) as EmployeeOut;
}

export async function createEmployee(
  body: EmployeeCreateIn,
): Promise<EmployeeOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/employees"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as {
      error?: { code?: string };
    };
    throw new EmployeesApiError(
      detail.error?.code ?? `http_${res.status}`,
      res.status,
    );
  }
  return (await res.json()) as EmployeeOut;
}

export async function patchEmployee(
  employeeId: string,
  body: EmployeePatchIn,
): Promise<EmployeeOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/employees/${employeeId}`), {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as {
      error?: { code?: string };
    };
    throw new EmployeesApiError(
      detail.error?.code ?? `http_${res.status}`,
      res.status,
    );
  }
  return (await res.json()) as EmployeeOut;
}