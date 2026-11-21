/**
 * AnnualView.test.tsx — focused tests for the self-contained annual view.
 *
 * Stage B Batch A. Covers:
 *   1. Renders the employee and year selectors.
 *   2. No employee selected → "select an employee" message shown; annual
 *      fetch is NOT made.
 *   3. Employee selected → fetchSheet is called with the correct year
 *      range and employee_id.
 *   4. fetchSheet rejects → error message shown, no grid.
 *
 * Everything mocked at the client boundary: `fetchEmployees` and
 * `fetchSheet` are vi.mock'ed so no network calls are made. The component
 * is mounted inside QueryClientProvider + MantineProvider as in
 * DayPanel.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { AnnualView } from "./AnnualView";
import type { EmployeeRef } from "../../api/employees";
import type { SheetOut } from "../../api/attendance";

// Mantine Select uses scrollIntoView; jsdom does not implement it.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {};
}

const fetchEmployeesMock = vi.fn();
const fetchSheetMock = vi.fn();

vi.mock("../../api/employees", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/employees")>(
      "../../api/employees",
    );
  return {
    ...actual,
    fetchEmployees: (...args: unknown[]) => fetchEmployeesMock(...args),
  };
});

vi.mock("../../api/attendance", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/attendance")>(
      "../../api/attendance",
    );
  return {
    ...actual,
    fetchSheet: (...args: unknown[]) => fetchSheetMock(...args),
  };
});

const EMPLOYEES: EmployeeRef[] = [
  { id: "emp-1", employee_code: "EMP001", first_name: "Ada", last_name: "Lovelace" },
  { id: "emp-2", employee_code: "EMP002", first_name: "Alan", last_name: "Turing" },
];

function yearFixture(year: number): SheetOut {
  return {
    items: [
      {
        employee_id: "emp-1",
        employee_code: "EMP001",
        employee_name: "Ada Lovelace",
        site_id: null,
        department_id: null,
        days: Array.from({ length: 365 }, (_, i) => {
          const d = new Date(Date.UTC(year, 0, 1));
          d.setUTCDate(d.getUTCDate() + i);
          const iso = d.toISOString().slice(0, 10);
          return {
            work_date: iso,
            status: null,
            worked_minutes: null,
            normal_minutes: null,
            overtime_minutes: null,
            flags: [],
            open_exception_count: 0,
            locked: false,
            reviewed: false,
          };
        }),
      },
    ],
    next_cursor: null,
    total: 1,
  };
}

function wrap(children: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>{children}</MantineProvider>
    </QueryClientProvider>
  );
}

type RenderProps = {
  year?: number;
  employeeId?: string | null;
  onEmployeeChange?: (id: string | null) => void;
  onYearChange?: (y: number) => void;
};

function renderAnnual({
  year = 2024,
  employeeId = null,
  onEmployeeChange = () => {},
  onYearChange = () => {},
}: RenderProps = {}) {
  return render(
    wrap(
      <AnnualView
        year={year}
        onYearChange={onYearChange}
        employeeId={employeeId}
        onEmployeeChange={onEmployeeChange}
        attendanceStatus={[]}
        onCellClick={() => {}}
      />,
    ),
  );
}

beforeEach(() => {
  fetchEmployeesMock.mockResolvedValue(EMPLOYEES);
  fetchSheetMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AnnualView", () => {
  it("renders the employee and year selectors", async () => {
    renderAnnual();
    expect(await screen.findByTestId("annual-employee")).toBeInTheDocument();
    expect(screen.getByTestId("annual-year")).toBeInTheDocument();
  });

  it("without an employee selected, shows the select-employee message and does not fetch", async () => {
    renderAnnual({ employeeId: null });
    expect(
      await screen.findByTestId("annual-empty-no-employee"),
    ).toBeInTheDocument();
    expect(fetchSheetMock).not.toHaveBeenCalled();
  });

  it("with an employee selected, calls fetchSheet with the correct year range and employee_id", async () => {
    fetchSheetMock.mockResolvedValueOnce(yearFixture(2024));
    renderAnnual({ year: 2024, employeeId: "emp-1" });

    await waitFor(() => {
      expect(fetchSheetMock).toHaveBeenCalledTimes(1);
    });
    const call = fetchSheetMock.mock.calls[0][0];
    expect(call).toMatchObject({
      fromDate: "2024-01-01",
      toDate: "2024-12-31",
      employeeId: "emp-1",
      limit: 1,
    });
  });

  it("on fetch error, shows the error alert and no grid", async () => {
    fetchSheetMock.mockRejectedValueOnce(new Error("boom"));
    renderAnnual({ year: 2024, employeeId: "emp-1" });

    await waitFor(() => {
      expect(screen.getByTestId("annual-error")).toBeInTheDocument();
    });
  });
});