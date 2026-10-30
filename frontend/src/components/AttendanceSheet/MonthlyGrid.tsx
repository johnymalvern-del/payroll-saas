import { Badge, Group, ScrollArea, Table, Text, Tooltip } from "@mantine/core";
import dayjs from "dayjs";
import type { SheetCell, SheetEmployee } from "../../api/attendance";
import { strings } from "../../lib/strings";

type Props = {
  fromDate: string;
  toDate: string;
  employees: SheetEmployee[];
  attendanceStatus: string[];
  onCellClick?: (employeeId: string, workDate: string) => void;
};

function buildDays(fromDate: string, toDate: string): string[] {
  if (!fromDate || !toDate) return [];
  const start = dayjs(fromDate);
  const end = dayjs(toDate);
  const days: string[] = [];
  let cur = start;
  while (cur.isBefore(end) || cur.isSame(end, "day")) {
    days.push(cur.format("YYYY-MM-DD"));
    cur = cur.add(1, "day");
  }
  return days;
}

function cellFor(employee: SheetEmployee, date: string): SheetCell | null {
  return employee.days.find((c) => c.work_date === date) ?? null;
}

function statusColor(status: string | null): string {
  switch (status) {
    case "worked":
      return "green";
    case "leave":
      return "blue";
    case "sick":
      return "orange";
    case "absent":
      return "red";
    case "day_off":
      return "gray";
    default:
      return "gray";
  }
}

function statusLabel(status: string | null): string {
  if (!status) return "\u2014";
  return status.replace("_", " ");
}

function CellView({
  cell,
  employeeId,
  workDate,
  onCellClick,
}: {
  cell: SheetCell | null;
  employeeId: string;
  workDate: string;
  onCellClick?: (employeeId: string, workDate: string) => void;
}) {
  if (!cell) {
    return (
      <Text size="xs" c="dimmed">
        {"\u2014"}
      </Text>
    );
  }
  const lines: string[] = [statusLabel(cell.status)];
  if (cell.worked_minutes !== null && cell.worked_minutes !== undefined) {
    lines.push(`${cell.worked_minutes} worked`);
  }
  if (cell.open_exception_count > 0) {
    lines.push(`${cell.open_exception_count} open exception(s)`);
  }
  if (cell.flags && cell.flags.length > 0) {
    lines.push(`flags: ${cell.flags.join(", ")}`);
  }
  if (cell.locked) lines.push("locked");
  if (cell.reviewed) lines.push("reviewed");

  const content = (
    <Group gap={4} wrap="nowrap" justify="center">
      {cell.status ? (
        <Badge size="xs" color={statusColor(cell.status)} variant="light">
          {statusLabel(cell.status)}
        </Badge>
      ) : (
        <Text size="xs" c="dimmed">
          {"\u2014"}
        </Text>
      )}
      {cell.open_exception_count > 0 ? (
        <Text size="xs" c="red" fw={700}>
          !
        </Text>
      ) : null}
    </Group>
  );

  return (
    <Tooltip label={lines.join(" \u00b7 ")} withinPortal>
      <div
        role={onCellClick ? "button" : undefined}
        tabIndex={onCellClick ? 0 : undefined}
        onClick={() => onCellClick?.(employeeId, workDate)}
        onKeyDown={(e) => {
          if (!onCellClick) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onCellClick(employeeId, workDate);
          }
        }}
        style={{ cursor: onCellClick ? "pointer" : "default" }}
      >
        {content}
      </div>
    </Tooltip>
  );
}

export function MonthlyGrid({
  fromDate,
  toDate,
  employees,
  attendanceStatus,
  onCellClick,
}: Props) {
  const days = buildDays(fromDate, toDate);
  const filterSet = attendanceStatus.length > 0 ? new Set(attendanceStatus) : null;

  const rows = employees
    .map((emp) => {
      const cells = days.map((d) => cellFor(emp, d));
      if (filterSet) {
        const anyMatch = cells.some(
          (c) => c && c.status && filterSet.has(c.status),
        );
        if (!anyMatch) return null;
      }
      return { emp, cells };
    })
    .filter(
      (r): r is { emp: SheetEmployee; cells: (SheetCell | null)[] } => r !== null,
    );

  if (rows.length === 0) {
    return <Text c="dimmed">{strings.attendance.empty}</Text>;
  }

  return (
    <ScrollArea type="auto" offsetScrollbars>
      <Table striped withTableBorder withColumnBorders stickyHeader highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th
              style={{
                minWidth: 200,
                position: "sticky",
                left: 0,
                background: "white",
                zIndex: 2,
              }}
            >
              {strings.attendance.employee}
            </Table.Th>
            {days.map((d) => (
              <Table.Th key={d} style={{ minWidth: 70, textAlign: "center" }}>
                {dayjs(d).format("DD")}
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map(({ emp, cells }) => (
            <Table.Tr key={emp.employee_id}>
              <Table.Td
                style={{
                  position: "sticky",
                  left: 0,
                  background: "white",
                  zIndex: 1,
                }}
              >
                <Text size="sm" fw={500}>
                  {emp.employee_name}
                </Text>
                <Text size="xs" c="dimmed">
                  {emp.employee_code}
                </Text>
              </Table.Td>
              {cells.map((c, i) => (
                <Table.Td key={days[i]} style={{ textAlign: "center" }}>
                  <CellView
                    cell={c}
                    employeeId={emp.employee_id}
                    workDate={days[i]}
                    onCellClick={onCellClick}
                  />
                </Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}
