import { Badge, ScrollArea, Table, Text } from "@mantine/core";
import dayjs from "dayjs";
import type { DailyRow } from "../../api/attendance";
import { strings } from "../../lib/strings";
import { colors } from "../../theme/colors";

type Props = {
  rows: DailyRow[];
  onRowClick?: (employeeId: string, workDate: string) => void;
};

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

// Same rule as the monthly grid: adjusted days are indistinguishable. Do not
// add an "adjust" column or badge here without breaking C2.
export function DailyList({ rows, onRowClick }: Props) {
  if (rows.length === 0) {
    return <Text c="dimmed">{strings.attendance.empty}</Text>;
  }
  return (
    <ScrollArea type="auto" offsetScrollbars>
      <Table striped withTableBorder withColumnBorders stickyHeader highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{strings.attendance.employee}</Table.Th>
            <Table.Th>{strings.attendance.daily.status}</Table.Th>
            <Table.Th>{strings.attendance.daily.firstIn}</Table.Th>
            <Table.Th>{strings.attendance.daily.lastOut}</Table.Th>
            <Table.Th>{strings.attendance.daily.worked}</Table.Th>
            <Table.Th>{strings.attendance.daily.overtime}</Table.Th>
            <Table.Th>{strings.attendance.daily.exceptions}</Table.Th>
            <Table.Th>{strings.attendance.daily.locked}</Table.Th>
            <Table.Th>{strings.attendance.daily.reviewed}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r) => (
            <Table.Tr
              key={`${r.employee_id}-${r.work_date}`}
              style={{ cursor: onRowClick ? "pointer" : "default" }}
              onClick={() => onRowClick?.(r.employee_id, r.work_date)}
            >
              <Table.Td>
                <Text size="sm" fw={500}>
                  {r.employee_name}
                </Text>
                <Text size="xs" c="dimmed">
                  {r.employee_code}
                </Text>
              </Table.Td>
              <Table.Td>
                {r.status ? (
                  <Badge size="xs" color={statusColor(r.status)} variant="light">
                    {r.status}
                  </Badge>
                ) : (
                  <Text size="xs" c="dimmed">
                    {"\u2014"}
                  </Text>
                )}
              </Table.Td>
              <Table.Td>
                {r.first_in ? dayjs(r.first_in).format("HH:mm") : "\u2014"}
              </Table.Td>
              <Table.Td>
                {r.last_out ? dayjs(r.last_out).format("HH:mm") : "\u2014"}
              </Table.Td>
              <Table.Td>{r.worked_minutes ?? "\u2014"}</Table.Td>
              <Table.Td>{r.overtime_minutes ?? "\u2014"}</Table.Td>
              <Table.Td>
                {r.open_exception_count > 0 ? (
                  <Badge size="xs" color={colors.problem}>
                    {r.open_exception_count}
                  </Badge>
                ) : (
                  <Text size="xs" c="dimmed">
                    {"\u2014"}
                  </Text>
                )}
              </Table.Td>
              <Table.Td>
                <Text size="xs" c={r.locked ? "gray" : "dimmed"}>
                  {r.locked ? strings.attendance.daily.yes : "\u2014"}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="xs" c={r.reviewed ? "blue" : "dimmed"}>
                  {r.reviewed ? strings.attendance.daily.yes : "\u2014"}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}
