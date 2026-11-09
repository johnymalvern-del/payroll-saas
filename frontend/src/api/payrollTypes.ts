import { absoluteUrl, wrappedFetch } from "./client";

export type EarningTypeOut = {
  id: string;
  name: string;
  code: string;
  calc_method: string;
  frequency: string;
  is_taxable: boolean;
  counts_for_uif: boolean;
  counts_for_sdl: boolean;
  proration_rule: string;
  is_system: boolean;
  is_active: boolean;
  row_version: number;
};

export type DeductionTypeOut = {
  id: string;
  name: string;
  code: string;
  category: string;
  priority: number;
  is_pre_tax: boolean;
  is_system: boolean;
  is_active: boolean;
  row_version: number;
};

export type EarningTypeListOut = { items: EarningTypeOut[] };
export type DeductionTypeListOut = { items: DeductionTypeOut[] };

async function _getList<T>(path: string): Promise<T> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(path), { method: "GET", credentials: "include" }),
  );
  if (!res.ok) {
    throw new Error(`http_${res.status}`);
  }
  return (await res.json()) as T;
}

export async function fetchEarningTypes(): Promise<EarningTypeListOut> {
  return _getList<EarningTypeListOut>("/api/v1/payroll/earning-types");
}

export async function fetchDeductionTypes(): Promise<DeductionTypeListOut> {
  return _getList<DeductionTypeListOut>("/api/v1/payroll/deduction-types");
}

// END OF FILE