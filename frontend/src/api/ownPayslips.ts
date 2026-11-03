import { absoluteUrl, wrappedFetch } from "./client";

export type PayslipMeRow = {
  id: string;
  pay_period_id: string;
  period_key: string;
  pay_date: string;
  status: string;
  gross: string;
  net: string;
  computed_at: string;
};

export type PayslipMeListOut = {
  items: PayslipMeRow[];
  next_cursor: string | null;
};

export type PayslipOut = {
  id: string;
  payroll_run_id: string;
  pay_period_id: string;
  employee_id: string;
  revision: number;
  status: string;
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
  pdf_object_key: string | null;
  predecessor_payslip_id: string | null;
  computed_at: string;
};

export class OwnPayslipsApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, status: number) {
    super(code);
    this.name = "OwnPayslipsApiError";
    this.code = code;
    this.status = status;
  }
}

async function parseError(res: Response): Promise<OwnPayslipsApiError> {
  const detail = (await res.json().catch(() => ({}))) as {
    error?: { code?: string };
  };
  return new OwnPayslipsApiError(
    detail.error?.code ?? `http_${res.status}`,
    res.status,
  );
}

export async function fetchMyPayslips(params: {
  limit?: number;
  cursor?: string | null;
}): Promise<PayslipMeListOut> {
  const qs = new URLSearchParams();
  qs.set("limit", String(params.limit ?? 100));
  if (params.cursor) qs.set("cursor", params.cursor);
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/payslips/me?${qs.toString()}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as PayslipMeListOut;
}

export async function fetchMyPayslip(id: string): Promise<PayslipOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/payslips/me/${id}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as PayslipOut;
}

export async function downloadMyPayslipPdf(id: string): Promise<void> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/payroll/payslips/me/${id}/pdf`), {
      credentials: "include",
    }),
  );
  if (!res.ok) throw await parseError(res);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = "payslip.pdf";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
