import { absoluteUrl, wrappedFetch } from "./client";

export type PayPeriodOut = {
  id: string;
  period_key: string;
  start_date: string;
  end_date: string;
  pay_date: string;
  status: string;
  cutoff_at: string;
  row_version: number;
};

export type PayPeriodListOut = {
  items: PayPeriodOut[];
  next_cursor: string | null;
};

export type PreviewSummaryRow = {
  employee_id: string;
  employee_code: string;
  employee_name: string;
  gross: string;
  paye: string;
  net: string;
  warnings: string[];
};

export type PreviewOut = {
  run_id: string;
  revision: number;
  status: string;
  unacknowledged_formulas: string[];
  items: PreviewSummaryRow[];
  next_cursor: string | null;
  raw_employee_count: number;
};

export type PreviewEmployeeLineOut = {
  earning_type_code: string;
  earning_type_name: string;
  rate_source: string | null;
  amount: string;
  minutes: number | null;
};

export type PreviewEmployeeDeductionOut = {
  deduction_type_code: string;
  deduction_type_name: string;
  amount: string;
};

export type PreviewEmployeeOut = {
  employee_id: string;
  employee_code: string;
  employee_name: string;
  pay_period_id: string;
  revision: number;
  status: string;
  gross: string;
  paye: string;
  net: string;
  warnings: string[];
  lines: PreviewEmployeeLineOut[];
  deductions: PreviewEmployeeDeductionOut[];
};

export type PayrollRunOut = {
  id: string;
  pay_period_id: string;
  kind: string;
  revision: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  error_code: string | null;
};

export type ReopenLogOut = {
  id: string;
  pay_period_id: string;
  reopened_by_user_id: string | null;
  reason: string;
  prior_revision: number;
  new_revision: number;
  occurred_at: string;
};

export type PayPeriodIn = {
  period_key: string;
  start_date: string;
  end_date: string;
  pay_date: string;
  cutoff_at: string;
};

export type SalarySheetRow = {
  employee_id: string;
  employee_code: string;
  employee_name: string;
  payslip_id: string;
  payslip_status: string;
  revision: number;
  basic_earnings: string;
  additional_earnings: string;
  gross: string;
  pre_tax_deductions: string;
  taxable_income: string;
  paye: string;
  uif_employee: string;
  uif_employer: string;
  sdl: string;
  other_deductions: string;
  reimbursements: string;
  net: string;
};

export type SalarySheetOut = {
  pay_period_id: string;
  pay_period_key: string;
  pay_period_status: string;
  figures_state: "preview" | "finalised" | "no_preview" | "preview_out_of_scope";
  run_id: string | null;
  revision: number | null;
  items: SalarySheetRow[];
  next_cursor: string | null;
};

export class PayPeriodsApiError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;
  constructor(code: string, status: number, details?: Record<string, unknown>) {
    super(code);
    this.name = "PayPeriodsApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

async function parseError(res: Response): Promise<PayPeriodsApiError> {
  const detail = (await res.json().catch(() => ({}))) as {
    error?: { code?: string; details?: Record<string, unknown> };
  };
  return new PayPeriodsApiError(
    detail.error?.code ?? `http_${res.status}`,
    res.status,
    detail.error?.details,
  );
}

export async function fetchPayPeriods(params: {
  status?: string;
  limit?: number;
  cursor?: string | null;
}): Promise<PayPeriodListOut> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  qs.set("limit", String(params.limit ?? 100));
  if (params.cursor) qs.set("cursor", params.cursor);
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/pay-periods?${qs.toString()}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as PayPeriodListOut;
}

export async function fetchPayPeriod(id: string): Promise<PayPeriodOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/pay-periods/${id}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as PayPeriodOut;
}

export async function createPayPeriod(body: PayPeriodIn): Promise<PayPeriodOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/payroll/pay-periods"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as PayPeriodOut;
}

export async function previewPayPeriod(params: {
  id: string;
  limit?: number;
  cursor?: string | null;
}): Promise<PreviewOut> {
  const qs = new URLSearchParams();
  qs.set("limit", String(params.limit ?? 100));
  if (params.cursor) qs.set("cursor", params.cursor);
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(`/api/v1/payroll/pay-periods/${params.id}/preview?${qs.toString()}`),
      { method: "POST", credentials: "include" },
    ),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as PreviewOut;
}

export async function previewPayPeriodEmployee(
  periodId: string,
  employeeId: string,
): Promise<PreviewEmployeeOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(
        `/api/v1/payroll/pay-periods/${periodId}/preview/${employeeId}`,
      ),
      { credentials: "include" },
    ),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as PreviewEmployeeOut;
}

export async function finalisePayPeriod(
  id: string,
  ackOpenExceptionsReason?: string | null,
): Promise<PayrollRunOut> {
  const body =
    ackOpenExceptionsReason && ackOpenExceptionsReason.trim()
      ? { ack_open_exceptions_reason: ackOpenExceptionsReason }
      : undefined;
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/pay-periods/${id}/finalise`), {
      method: "POST",
      credentials: "include",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as PayrollRunOut;
}

export async function reopenPayPeriod(
  id: string,
  reason: string,
): Promise<ReopenLogOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/pay-periods/${id}/reopen`), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as ReopenLogOut;
}

export async function fetchReopenLog(id: string): Promise<ReopenLogOut[]> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/pay-periods/${id}/reopen-log`), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as ReopenLogOut[];
}

export type PreviewEmployeeAsOfOut = {
  employee_id: string;
  employee_code: string;
  employee_name: string;
  pay_period_id: string;
  revision: number | null;
  status: string;
  as_of: string | null;
  available: boolean;
  reason_unavailable: string | null;
  gross: string | null;
  paye: string | null;
  net: string | null;
  warnings: string[];
  lines: {
    earning_type_code: string;
    earning_type_name: string;
    rate_source: string;
    amount: string;
    minutes: number | null;
  }[];
  deductions: {
    deduction_type_code: string;
    deduction_type_name: string;
    amount: string;
  }[];
  unacknowledged_formulas: string[];
  demo_values: boolean;
};

export async function previewEmployeeAsOf(
  periodId: string,
  employeeId: string,
  asOf: string,
): Promise<PreviewEmployeeAsOfOut> {
  const url = `/api/v1/payroll/pay-periods/${periodId}/preview/${employeeId}?as_of=${encodeURIComponent(asOf)}`;
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) {
    const errBody = (await res.json().catch(() => ({}))) as {
      error?: { code?: string; message?: string; details?: unknown };
    };
    const apiMsg =
      errBody.error?.message ??
      (res.status === 403 ? "forbidden" : `HTTP ${res.status}`);
    const apiCode = errBody.error?.code ?? "http_error";
    const e = new Error(apiMsg) as Error & {
      code?: string;
      status?: number;
      details?: unknown;
    };
    e.code = apiCode;
    e.status = res.status;
    e.details = errBody.error?.details ?? null;
    throw e;
  }
  return (await res.json()) as PreviewEmployeeAsOfOut;
}

export async function fetchSalarySheet(params: {
  periodId: string;
  q?: string;
  limit?: number;
  cursor?: string | null;
}): Promise<SalarySheetOut> {
  const qs = new URLSearchParams();
  qs.set("limit", String(params.limit ?? 100));
  if (params.q) qs.set("q", params.q);
  if (params.cursor) qs.set("cursor", params.cursor);
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(
        `/api/v1/payroll/pay-periods/${params.periodId}/salary-sheet?${qs.toString()}`,
      ),
      { credentials: "include" },
    ),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as SalarySheetOut;
}