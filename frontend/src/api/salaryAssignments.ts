import { absoluteUrl, wrappedFetch } from "./client";

export type OverrideKind = "employee_earning" | "employee_deduction";

export type OverrideManualIdIn = {
  kind: OverrideKind;
  id: string;
};

export type AssignmentSubmitIn = {
  employee_id: string;
  structure_id: string;
  effective_from: string;
  idempotency_key?: string | null;
  override_manual_ids?: OverrideManualIdIn[];
};

export type AssignmentOut = {
  id: string;
  employee_id: string;
  structure_id: string;
  effective_from: string;
  effective_to: string | null;
  status: string;
  idempotency_key: string | null;
  submitted_by_user_id: string | null;
  submitted_at: string;
  decided_by_user_id: string | null;
  decided_at: string | null;
  decision_note: string | null;
  failure_detail: string | null;
  override_manual_ids: OverrideManualIdIn[];
  row_version: number;
  created_at: string;
  updated_at: string;
};

export type ChangeRequestChildOut = {
  id: string;
  kind: string;
  employee_id: string;
  status: string;
  applied_entity_id: string | null;
  decision_note: string | null;
};

export type AssignmentDetailOut = AssignmentOut & {
  children: ChangeRequestChildOut[];
};

export type AttemptOut = {
  id: string;
  assignment_id: string;
  attempted_by_user_id: string | null;
  attempted_at: string;
  outcome: string;
  failure_detail: string | null;
};

export type AssignmentListOut = { items: AssignmentOut[] };
export type AttemptListOut = { items: AttemptOut[] };

export type ManualOverlapOut = {
  kind: string;
  id: string;
  component_kind: string;
  component_type_id: string;
  effective_from: string;
  effective_to: string | null;
  status: string;
};

export type StructureOwnedOverlapOut = {
  kind: string;
  id: string;
  component_kind: string;
  component_type_id: string;
  effective_from: string;
  effective_to: string | null;
};

export type CheckCollisionsIn = {
  employee_id: string;
  structure_id: string;
  effective_from: string;
  override_manual_ids?: OverrideManualIdIn[];
};

export type CheckCollisionsOut = {
  employee_id: string;
  structure_id: string;
  effective_from: string;
  manual: ManualOverlapOut[];
  structure_owned: StructureOwnedOverlapOut[];
};

export class AssignmentApiError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;
  constructor(code: string, status: number, details?: Record<string, unknown>) {
    super(code);
    this.name = "AssignmentApiError";
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
    throw new AssignmentApiError(
      body.error?.code ?? `http_${res.status}`,
      res.status,
      body.error?.details,
    );
  }
  return (await res.json()) as T;
}

export async function submitAssignment(
  body: AssignmentSubmitIn,
): Promise<AssignmentOut> {
  const res = await wrappedFetch(
    new Request(absoluteUrl("/api/v1/payroll/employee-salary-assignments"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  return _handle<AssignmentOut>(res);
}

export async function checkCollisions(
  body: CheckCollisionsIn,
): Promise<CheckCollisionsOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl("/api/v1/payroll/employee-salary-assignments/check-collisions"),
      {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  );
  return _handle<CheckCollisionsOut>(res);
}

export async function fetchAssignment(
  assignmentId: string,
): Promise<AssignmentDetailOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(`/api/v1/payroll/employee-salary-assignments/${assignmentId}`),
      { method: "GET", credentials: "include" },
    ),
  );
  return _handle<AssignmentDetailOut>(res);
}

export async function fetchAttempts(
  assignmentId: string,
): Promise<AttemptListOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(
        `/api/v1/payroll/employee-salary-assignments/${assignmentId}/attempts`,
      ),
      { method: "GET", credentials: "include" },
    ),
  );
  return _handle<AttemptListOut>(res);
}

export async function fetchEmployeeAssignments(
  employeeId: string,
): Promise<AssignmentListOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(`/api/v1/payroll/employees/${employeeId}/salary-assignments`),
      { method: "GET", credentials: "include" },
    ),
  );
  return _handle<AssignmentListOut>(res);
}

export async function approveAssignment(
  assignmentId: string,
): Promise<AssignmentDetailOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(
        `/api/v1/payroll/employee-salary-assignments/${assignmentId}/approve`,
      ),
      { method: "POST", credentials: "include" },
    ),
  );
  return _handle<AssignmentDetailOut>(res);
}

export async function rejectAssignment(
  assignmentId: string, note: string,
): Promise<AssignmentOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(
        `/api/v1/payroll/employee-salary-assignments/${assignmentId}/reject`,
      ),
      {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
      },
    ),
  );
  return _handle<AssignmentOut>(res);
}

export async function cancelAssignment(
  assignmentId: string,
): Promise<AssignmentOut> {
  const res = await wrappedFetch(
    new Request(
      absoluteUrl(
        `/api/v1/payroll/employee-salary-assignments/${assignmentId}/cancel`,
      ),
      { method: "POST", credentials: "include" },
    ),
  );
  return _handle<AssignmentOut>(res);
}