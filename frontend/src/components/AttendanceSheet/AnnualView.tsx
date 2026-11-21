/**
 * AnnualView — self-contained annual attendance view for one employee.
 *
 * Stage B Batch A. Owns its own employee + year selection state (D2=a).
 * The parent page only supplies `attendanceStatus` (from the global filter
 * bar) and `onCellClick` (to open the day panel). Everything else —
 * employee selector, year selector, query, loading/error/empty states,
 * and the grid — lives here.
 *
 * Data flow:
 *   - fetchEmployees() → flat EmployeeRef[] (all employees in scope).
 *   - When employeeId is null, no annual fetch is made; a "select an
 *     employee" message renders instead.
 *   - When employeeId is set, fetchSheet({ fromDate, toDate, employeeId,
 *     limit: 1 }) is called. The backend filters by employee_id, so the
 *     response contains exactly the selected employee's year.
 *   - The response is passed to AnnualGrid, which renders 12 stacked
 *     MonthlyGrid sections.
 *
 * Why limit: 1 — the annual query is for one employee. limit: 1 tells
 * the backend to return at most one employee row, which is the selected
 * employee (the employee_id filter guarantees it). Pagination is not
 * needed.
 */
import { useQuery } from "@tanstack/react-query";
import { Alert, Group, Loader, Select, Stack, Text } from "@mantine/core";
import dayjs from "dayjs";
import { fetchEmployees } from "../../api/employees";
import { fetchSheet } from "../../api/attendance";
import { AnnualGrid } from "./AnnualGrid";
import { strings } from "../../lib/strings";
import { colors } from "../../theme/colors";

type Props = {
  year: number;
  onYearChange: (y: number) => void;
  employeeId: string | null;
  onEmployeeChange: (id: string | null) => void;
  attendanceStatus: string[];
  onCellClick: (employeeId: string, workDate: string) => void;
};

const YEAR_OPTIONS_COUNT = 5;

function recentYears(currentYear: number): number[] {
  const out: number[] = [];
  for (let i = 0; i < YEAR_OPTIONS_COUNT; i += 1) {
    out.push(currentYear - i);
  }
  return out;
}

export function AnnualView({
  year,
  onYearChange,
  employeeId,
  onEmployeeChange,
  attendanceStatus,
  onCellClick,
}: Props) {
  const employeesQuery = useQuery({
    queryKey: ["refs", "employees"],
    queryFn: fetchEmployees,
    staleTime: 5 * 60_000,
  });
  const employees = employeesQuery.data ?? [];
  const employeeOptions = employees.map((e) => ({
    value: e.id,
    label: `${e.first_name} ${e.last_name} (${e.employee_code})`,
  }));

  const fromDate = `${year}-01-01`;
  const toDate = `${year}-12-31`;

  const annualQuery = useQuery({
    queryKey: ["attendance", "sheet", "annual", year, employeeId],
    queryFn: () =>
      fetchSheet({
        fromDate,
        toDate,
        employeeId,
        limit: 1,
      }),
    enabled: !!employeeId,
    staleTime: 30_000,
  });

  const yearOptions = recentYears(dayjs().year()).map((y) => ({
    value: String(y),
    label: String(y),
  }));

  return (
    <Stack gap="md">
      <Group gap="sm" align="flex-end">
        <Select
          label={strings.attendance.employee}
          placeholder={strings.attendance.annualSelectEmployee}
          data={employeeOptions}
          value={employeeId}
          onChange={onEmployeeChange}
          searchable
          clearable
          disabled={employeesQuery.isLoading}
          style={{ minWidth: 280 }}
          data-testid="annual-employee"
        />
        <Select
          label={strings.attendance.annualSelectYear}
          data={yearOptions}
          value={String(year)}
          onChange={(v) => {
            if (v) onYearChange(Number(v));
          }}
          allowDeselect={false}
          data-testid="annual-year"
        />
      </Group>

      {!employeeId ? (
        <Text c="dimmed" data-testid="annual-empty-no-employee">
          {strings.attendance.annualSelectEmployee}
        </Text>
      ) : annualQuery.isLoading ? (
        <Group justify="center" p="xl">
          <Loader />
          <Text size="sm" c="dimmed">
            {strings.attendance.annualLoading}
          </Text>
        </Group>
      ) : annualQuery.isError ? (
        <Alert color={colors.problem} data-testid="annual-error">
          {strings.attendance.annualError}
        </Alert>
      ) : (annualQuery.data?.items ?? []).length === 0 ? (
        <Alert color={colors.inactive} data-testid="annual-empty-result">
          {strings.attendance.annualEmpty}
        </Alert>
      ) : (
        <AnnualGrid
          year={year}
          employees={annualQuery.data?.items ?? []}
          attendanceStatus={attendanceStatus}
          onCellClick={onCellClick}
        />
      )}
    </Stack>
  );
}