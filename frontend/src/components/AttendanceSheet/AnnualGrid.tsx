/**
 * AnnualGrid — 12 stacked MonthlyGrid sections for one calendar year.
 *
 * Stage B Batch A. Each month is rendered by the existing MonthlyGrid
 * with the month's [fromDate, toDate] boundaries. No new cell-rendering
 * logic. No new empty-state logic. No new employee-column logic. If
 * MonthlyGrid changes, AnnualGrid picks the change up automatically.
 *
 * The wide-grid alternative (365 columns in one table) was rejected as
 * unreadable. The 12-section stack keeps the monthly metaphor and the
 * existing filter bar's per-month affordances.
 *
 * The "annual month header" strings.attendance.annualMonthHeader is
 * called once per month; it is currently identity, so we can change
 * "January" to "January 2024" in one place later if desired.
 */
import { Divider, Stack, Text } from "@mantine/core";
import dayjs from "dayjs";
import type { SheetEmployee } from "../../api/attendance";
import { MonthlyGrid } from "./MonthlyGrid";
import { strings } from "../../lib/strings";

type Props = {
  year: number;
  employees: SheetEmployee[];
  attendanceStatus: string[];
  onCellClick?: (employeeId: string, workDate: string) => void;
};

const MONTH_INDEXES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];

function monthRange(year: number, monthIndex: number): { fromDate: string; toDate: string; label: string } {
  const start = dayjs().year(year).month(monthIndex).startOf("month");
  const end = start.endOf("month");
  return {
    fromDate: start.format("YYYY-MM-DD"),
    toDate: end.format("YYYY-MM-DD"),
    label: start.format("MMMM YYYY"),
  };
}

export function AnnualGrid({
  year,
  employees,
  attendanceStatus,
  onCellClick,
}: Props) {
  if (employees.length === 0) {
    return <Text c="dimmed">{strings.attendance.empty}</Text>;
  }

  return (
    <Stack gap="md">
      {MONTH_INDEXES.map((m) => {
        const { fromDate, toDate, label } = monthRange(year, m);
        return (
          <Stack key={`${year}-${m}`} gap="xs">
            <Text fw={600} size="sm">
              {strings.attendance.annualMonthHeader(label)}
            </Text>
            <MonthlyGrid
              fromDate={fromDate}
              toDate={toDate}
              employees={employees}
              attendanceStatus={attendanceStatus}
              onCellClick={onCellClick}
            />
            {m < MONTH_INDEXES.length - 1 ? <Divider /> : null}
          </Stack>
        );
      })}
    </Stack>
  );
}