import { useQuery } from "@tanstack/react-query";
import {
  Badge,
  Drawer,
  Group,
  Loader,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import dayjs from "dayjs";
import { fetchDay } from "../../api/attendance";
import { strings } from "../../lib/strings";

type Props = {
  employeeId: string;
  workDate: string;
  onClose: () => void;
};

// CRITICAL: this panel must NEVER render adjustment markers. Adjusted days
// are indistinguishable from clocked days by design (C2). Adjustments are
// visible only through the audit log. Any future prop that surfaces an
// adjustment must not be rendered here.
export function DayPanel({ employeeId, workDate, onClose }: Props) {
  const day = useQuery({
    queryKey: ["attendance", "day", employeeId, workDate],
    queryFn: () => fetchDay(employeeId, workDate),
    staleTime: 30_000,
  });

  const dateLabel = dayjs(workDate).format("ddd, DD MMM YYYY");

  return (
    <Drawer
      opened
      onClose={onClose}
      position="right"
      size="md"
      title={strings.attendance.dayPanel.title}
    >
      {day.isLoading ? (
        <Group justify="center" p="xl">
          <Loader />
        </Group>
      ) : day.isError || !day.data ? (
        <Text c="red">{strings.attendance.dayPanel.error}</Text>
      ) : (
        <Stack gap="md">
          <Stack gap={2}>
            <Text fw={600}>{day.data.employee_name}</Text>
            <Text size="sm" c="dimmed">
              {day.data.employee_code} · {dateLabel}
            </Text>
          </Stack>

          <Group gap="xs">
            {day.data.status ? (
              <Badge variant="light">{day.data.status}</Badge>
            ) : (
              <Badge variant="light" color="gray">
                {strings.attendance.dayPanel.noStatus}
              </Badge>
            )}
            {day.data.locked ? (
              <Badge color="gray">{strings.attendance.dayPanel.locked}</Badge>
            ) : null}
            {day.data.reviewed ? (
              <Badge color="blue">{strings.attendance.dayPanel.reviewed}</Badge>
            ) : null}
            {day.data.open_exception_count > 0 ? (
              <Badge color="red">
                {day.data.open_exception_count} {strings.attendance.dayPanel.openExceptions}
              </Badge>
            ) : null}
          </Group>

          <Group gap="lg">
            <Stack gap={0}>
              <Text size="xs" c="dimmed">
                {strings.attendance.dayPanel.firstIn}
              </Text>
              <Text>{day.data.first_in ?? "\u2014"}</Text>
            </Stack>
            <Stack gap={0}>
              <Text size="xs" c="dimmed">
                {strings.attendance.dayPanel.lastOut}
              </Text>
              <Text>{day.data.last_out ?? "\u2014"}</Text>
            </Stack>
            <Stack gap={0}>
              <Text size="xs" c="dimmed">
                {strings.attendance.dayPanel.worked}
              </Text>
              <Text>
                {day.data.worked_minutes === null
                  ? "\u2014"
                  : `${day.data.worked_minutes} ${strings.attendance.dayPanel.minutes}`}
              </Text>
            </Stack>
            <Stack gap={0}>
              <Text size="xs" c="dimmed">
                {strings.attendance.dayPanel.overtime}
              </Text>
              <Text>
                {day.data.overtime_minutes === null
                  ? "\u2014"
                  : `${day.data.overtime_minutes} ${strings.attendance.dayPanel.minutes}`}
              </Text>
            </Stack>
          </Group>

          {day.data.flags.length > 0 ? (
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                {strings.attendance.dayPanel.flags}
              </Text>
              <Group gap="xs">
                {day.data.flags.map((f) => (
                  <Badge key={f} variant="light" color="orange">
                    {f}
                  </Badge>
                ))}
              </Group>
            </Stack>
          ) : null}

          <Stack gap={4}>
            <Text size="sm" fw={500}>
              {strings.attendance.dayPanel.punches}
            </Text>
            {day.data.punches.length === 0 ? (
              <Text size="sm" c="dimmed">
                {strings.attendance.dayPanel.noPunches}
              </Text>
            ) : (
              <Table striped withTableBorder>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{strings.attendance.dayPanel.time}</Table.Th>
                    <Table.Th>{strings.attendance.dayPanel.direction}</Table.Th>
                    <Table.Th>{strings.attendance.dayPanel.source}</Table.Th>
                    <Table.Th>{strings.attendance.dayPanel.confidence}</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {day.data.punches.map((p) => (
                    <Table.Tr key={p.id}>
                      <Table.Td>
                        {dayjs(p.punch_time).format("HH:mm:ss")}
                      </Table.Td>
                      <Table.Td>{p.direction}</Table.Td>
                      <Table.Td>{p.source}</Table.Td>
                      <Table.Td>
                        {p.confidence === null ? "\u2014" : p.confidence}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
          </Stack>

          <Stack gap={4}>
            <Text size="sm" fw={500}>
              {strings.attendance.dayPanel.exceptions}
            </Text>
            {day.data.exceptions.length === 0 ? (
              <Text size="sm" c="dimmed">
                {strings.attendance.dayPanel.noExceptions}
              </Text>
            ) : (
              <Stack gap={4}>
                {day.data.exceptions.map((ex) => (
                  <Group key={ex.id} gap="xs" wrap="nowrap">
                    <Badge
                      variant="light"
                      color={ex.status === "open" ? "red" : "gray"}
                    >
                      {ex.status}
                    </Badge>
                    <Text size="sm">{ex.type}</Text>
                    <Text size="sm" c="dimmed">
                      {ex.message}
                    </Text>
                  </Group>
                ))}
              </Stack>
            )}
          </Stack>
        </Stack>
      )}
    </Drawer>
  );
}
