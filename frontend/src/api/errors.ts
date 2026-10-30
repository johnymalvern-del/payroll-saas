export type ApiError = {
  code: string;
  message: string;
  status: number;
  details?: unknown;
};

const MESSAGES: Record<string, string> = {
  forbidden: "You do not have permission to do that.",
  not_found: "That record could not be found.",
  record_changed: "Someone else changed this record. Reload and try again.",
  validation_error: "Some fields are invalid. Check the highlighted fields.",
  period_locked: "That pay period is locked. Reopen it before making changes.",
  period_not_locked: "That pay period is not locked.",
  formula_unacknowledged: "Acknowledge all payroll formulas before finalising.",
  calc_method_unsupported: "This earning type is not supported yet.",
  statutory_table_missing: "Statutory tables are missing for that pay date.",
  missing_date_of_birth: "This employee has no date of birth on file.",
  sdl_applies_unset: "Set payroll.sdl_applies before running payroll.",
  age_reference_date_unset:
    "Set payroll.age_reference_date before running payroll.",
  self_approval_forbidden: "You cannot approve a request you submitted.",
  not_requester: "Only the requester can cancel this change.",
  not_pending: "That request is no longer pending.",
  day_locked: "This day is locked and cannot be adjusted.",
  cannot_adjust_own: "You cannot adjust your own attendance.",
  invalid_reason_code: "Choose a valid reason code.",
  dry_run_token_missing: "Run the dry-run step again before confirming.",
  dry_run_token_expired: "The dry-run token has expired. Run dry-run again.",
  code_taken: "That code is already in use.",
  system_row: "System rows cannot be edited or deactivated.",
  invalid_cursor: "The pagination cursor is malformed.",
  tenant_missing: "Tenant not specified.",
  tenant_not_found: "That tenant was not found.",
};

export function mapErrorCode(code: string | undefined, fallback?: string): string {
  if (code) {
    const m = MESSAGES[code];
    if (m) return m;
  }
  return fallback ?? "Something went wrong. Please try again.";
}

export async function parseApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as
      | { error?: { code?: unknown; message?: unknown; details?: unknown } }
      | null;
    const err = body?.error ?? {};
    const code = typeof err.code === "string" ? err.code : "http_error";
    const message =
      typeof err.message === "string" ? err.message : response.statusText;
    return { code, message, status: response.status, details: err.details };
  } catch {
    return {
      code: "http_error",
      message: response.statusText,
      status: response.status,
    };
  }
}
