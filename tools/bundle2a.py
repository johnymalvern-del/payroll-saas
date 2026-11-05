"""Bundle 2A: API modules for sites, branches, departments, shifts, rate-rules,
work-patterns, public-holidays. Same auth-header pattern as devices.ts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
F = ROOT / "frontend" / "src" / "api"

SHARED_HEADER = '''import { getAccessToken } from "./client";
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

'''

FILES = {
    "sites.ts": SHARED_HEADER + '''export type Site = {
  id: string;
  branch_id: string;
  name: string;
  code: string;
  site_type: string | null;
  address: string | null;
  timezone: string | null;
  latitude: number | string | null;
  longitude: number | string | null;
  geofence_radius_m: number | null;
  is_active: boolean;
  row_version: number;
};

export type SiteCreateIn = {
  branch_id: string;
  name: string;
  code: string;
  site_type?: string | null;
  address?: string | null;
  timezone?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  geofence_radius_m?: number | null;
};

export type SitePatchIn = Partial<SiteCreateIn> & { row_version: number; is_active?: boolean };
export type SiteListOut = { items: Site[]; next_cursor?: string | null; total?: number | null };

export const sitesApi = {
  list: () => req<SiteListOut>("GET", "/sites"),
  create: (b: SiteCreateIn) => req<Site>("POST", "/sites", b),
  patch: (id: string, b: SitePatchIn) => req<Site>("PATCH", `/sites/${id}`, b),
  remove: (id: string) => req<void>("DELETE", `/sites/${id}`),
};
''',

    "branches.ts": SHARED_HEADER + '''export type Branch = {
  id: string;
  name: string;
  code: string;
  address: string | null;
  is_active: boolean;
  row_version: number;
};

export type BranchCreateIn = { name: string; code: string; address?: string | null };
export type BranchPatchIn = Partial<BranchCreateIn> & { row_version: number; is_active?: boolean };
export type BranchListOut = { items: Branch[]; next_cursor?: string | null; total?: number | null };

export const branchesApi = {
  list: () => req<BranchListOut>("GET", "/branches"),
  create: (b: BranchCreateIn) => req<Branch>("POST", "/branches", b),
  patch: (id: string, b: BranchPatchIn) => req<Branch>("PATCH", `/branches/${id}`, b),
  remove: (id: string) => req<void>("DELETE", `/branches/${id}`),
};
''',

    "departments.ts": SHARED_HEADER + '''export type Department = {
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
''',

    "shifts.ts": SHARED_HEADER + '''export type Shift = {
  id: string;
  name: string;
  start_time: string;
  length_minutes: number;
  unpaid_break_minutes: number;
  paid_break_minutes: number;
  grace_late_minutes: number;
  grace_early_minutes: number;
  rounding_minutes: number;
  rounding_mode: string;
  min_overtime_minutes: number;
  overtime_requires_approval: boolean;
  max_shift_minutes: number;
  match_tolerance_minutes: number;
  salaried_premium_mode: string;
  grace_mode: string;
  pay_early_arrival: boolean;
  is_active: boolean;
  row_version: number;
};

export type ShiftCreateIn = {
  name: string;
  start_time: string;
  length_minutes: number;
  max_shift_minutes: number;
  unpaid_break_minutes?: number;
  paid_break_minutes?: number;
  grace_late_minutes?: number;
  grace_early_minutes?: number;
  rounding_minutes?: number;
  rounding_mode?: string;
  min_overtime_minutes?: number;
  overtime_requires_approval?: boolean;
  match_tolerance_minutes?: number;
  salaried_premium_mode?: string;
  grace_mode?: string;
  pay_early_arrival?: boolean;
};

export type ShiftPatchIn = Partial<ShiftCreateIn> & { row_version: number; is_active?: boolean };
export type ShiftListOut = { items: Shift[]; next_cursor?: string | null; total?: number | null };

export const shiftsApi = {
  list: () => req<ShiftListOut>("GET", "/shifts"),
  create: (b: ShiftCreateIn) => req<Shift>("POST", "/shifts", b),
  patch: (id: string, b: ShiftPatchIn) => req<Shift>("PATCH", `/shifts/${id}`, b),
  remove: (id: string) => req<void>("DELETE", `/shifts/${id}`),
};
''',

    "rateRules.ts": SHARED_HEADER + '''export type ShiftRateRule = {
  id: string;
  shift_id: string;
  day_type: string;
  kind: string;
  tier: number;
  tier_up_to_minutes: number | null;
  method: string;
  value: string | number;
  flat_unit: string | null;
  effective_from: string;
  effective_to: string | null;
};

export type ShiftRateRuleCreateIn = {
  day_type: string;
  kind: string;
  tier: number;
  tier_up_to_minutes?: number | null;
  method: string;
  value: number | string;
  flat_unit?: string | null;
  effective_from: string;
  effective_to?: string | null;
};

export type ShiftRateRuleListOut = {
  items: ShiftRateRule[];
  next_cursor?: string | null;
  total?: number | null;
};

export const rateRulesApi = {
  list: (shiftId: string) =>
    req<ShiftRateRuleListOut>("GET", `/shifts/${shiftId}/rate-rules`),
  create: (shiftId: string, b: ShiftRateRuleCreateIn) =>
    req<ShiftRateRule>("POST", `/shifts/${shiftId}/rate-rules`, b),
  remove: (shiftId: string, ruleId: string) =>
    req<void>("DELETE", `/shifts/${shiftId}/rate-rules/${ruleId}`),
};
''',

    "workPatterns.ts": SHARED_HEADER + '''export type WorkPatternDay = {
  id: string;
  work_pattern_id: string;
  day_index: number;
  is_expected: boolean;
  expected_shift_id: string | null;
};

export type WorkPattern = {
  id: string;
  name: string;
  cycle_length_days: number;
  anchor_date: string;
  is_active: boolean;
  row_version: number;
  days: WorkPatternDay[];
};

export type WorkPatternDayIn = {
  day_index: number;
  is_expected: boolean;
  expected_shift_id?: string | null;
};

export type WorkPatternCreateIn = {
  name: string;
  cycle_length_days: number;
  anchor_date: string;
  days: WorkPatternDayIn[];
};

export type WorkPatternPatchIn = Partial<WorkPatternCreateIn> & {
  row_version: number;
  is_active?: boolean;
};

export type WorkPatternListOut = {
  items: Omit<WorkPattern, "days">[];
  next_cursor?: string | null;
  total?: number | null;
};

export const workPatternsApi = {
  list: () => req<WorkPatternListOut>("GET", "/work-patterns"),
  get: (id: string) => req<WorkPattern>("GET", `/work-patterns/${id}`),
  create: (b: WorkPatternCreateIn) =>
    req<WorkPattern>("POST", "/work-patterns", b),
  patch: (id: string, b: WorkPatternPatchIn) =>
    req<WorkPattern>("PATCH", `/work-patterns/${id}`, b),
  remove: (id: string) => req<void>("DELETE", `/work-patterns/${id}`),
};
''',

    "publicHolidays.ts": SHARED_HEADER + '''export type PublicHoliday = {
  id: string;
  holiday_date: string;
  name: string;
  site_id: string | null;
  department_id: string | null;
  is_working_day_override: boolean;
  is_active: boolean;
  row_version: number;
};

export type PublicHolidayCreateIn = {
  holiday_date: string;
  name: string;
  site_id?: string | null;
  department_id?: string | null;
  is_working_day_override?: boolean;
};

export type PublicHolidayPatchIn = {
  row_version: number;
  holiday_date?: string;
  name?: string;
  is_working_day_override?: boolean;
  is_active?: boolean;
};

export type PublicHolidayListOut = {
  items: PublicHoliday[];
  next_cursor?: string | null;
  total?: number | null;
};

export const publicHolidaysApi = {
  list: () => req<PublicHolidayListOut>("GET", "/public-holidays"),
  create: (b: PublicHolidayCreateIn) =>
    req<PublicHoliday>("POST", "/public-holidays", b),
  patch: (id: string, b: PublicHolidayPatchIn) =>
    req<PublicHoliday>("PATCH", `/public-holidays/${id}`, b),
  remove: (id: string) => req<void>("DELETE", `/public-holidays/${id}`),
};
''',
}

for name, content in FILES.items():
    (F / name).write_text(content, encoding="utf-8")
    print(f"wrote src/api/{name}")