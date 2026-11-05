import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Divider,
  Drawer,
  Group,
  Loader,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import dayjs from "dayjs";
import {
  fetchDay,
  fetchEmployeeById,
  fetchExceptionsForDay,
  markReviewed,
  type SegmentOut,
} from "../../api/attendance";
import { strings } from "../../lib/strings";
import { colors } from "../../theme/colors";

type Props = {
  employeeId: string;
  workDate: string;
  onClose: () => void;
  reviewedOverride?: boolean;
};

function dayTypeLabel(dayType: string | null | undefined): string {
  if (!dayType) return "Weekday";
  const t = dayType.toLowerCase();
  if (t.includes("holiday")) return "Public holiday";
  if (t === "saturday") return "Saturday";
  if (t === "sunday") return "Sunday";
  if (t === "weekday") return "Weekday";
  return dayType.replace(/_/g, " ");
}

function rateLabel(method: string, value: string): string {
  if (method === "multiplier") return `\u00d7 ${value}`;
  if (method === "flat") return value;
  return `${method}: ${value}`;
}

export function DayPanel({ employeeId, workDate, onClose, reviewedOverride }: Props) {
  const qc = useQueryClient();

  const day = useQuery({
    queryKey: ["attendance", "day", employeeId, workDate],
    queryFn: () => fetchDay(employeeId, workDate),
    staleTime: 30_000,
    retry: false,
  });

  const emp = useQuery({
    queryKey: ["refs", "employee", employeeId],
    queryFn: () => fetchEmployeeById(employeeId),
    staleTime: 5 * 60_000,
  });

  const exceptions = useQuery({
    queryKey: ["attendance", "day", employeeId, workDate, "exceptions"],
    queryFn: () => fetchExceptionsForDay(employeeId, workDate),
    staleTime: 30_000,
  });

  const shifts = useQuery({
    queryKey: ["refs", "shifts"],
    queryFn: async () => {
      const res = await fetch("/api/v1/shifts?limit=500", { credentials: "include" });
      if (!res.ok) return [] as { id: string; name: string }[];
      const body = (await res.json().catch(() => ({}))) as { items?: { id: string; name: string }[] };
      return body.items ?? [];
    },
    staleTime: 5 * 60_000,
  });

  const mark = useMutation({
    mutationFn: () => markReviewed({ fromDate: workDate, toDate: workDate }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["attendance"] });
    },
  });

  const dateLabel = dayjs(workDate).format("ddd, DD MMM YYYY");
  const employeeName = emp.data
    ? `${emp.data.first_name} ${emp.data.last_name}`.trim()
    : "";
  const employeeCode = emp.data?.employee_code ?? "";
  const is404 =
    day.isError &&
    day.error instanceof Error &&
    day.error.message.includes("404");

  const reviewed = reviewedOverride === true || (day.data?.reviewed === true);

  return (
    <Drawer
      opened
      onClose={onClose}
      position="right"
      size="lg"
      title={strings.attendance.dayPanel.title}
    >
      {day.isLoading ? (
        <Group justify="center" p="xl">
          <Loader />
        </Group>
      ) : is404 ? (
        <Stack gap="md">
          <Text fw={600}>{employeeName || employeeId}</Text>
          <Text size="sm" c="dimmed">
            {employeeCode ? employeeCode + " \u00b7 " : ""}
            {dateLabel}
          </Text>
          <Alert color={colors.inactive}>
            No attendance record for this day.
          </Alert>
        </Stack>
      ) : day.isError || !day.data ? (
        <Text c={colors.problem}>{strings.attendance.dayPanel.error}</Text>
      ) : (
        <Stack gap="md">
          <Stack gap={2}>
            <Text fw={600}>
              {employeeName || "Loading employee\u2026"}
            </Text>
            <Text size="sm" c="dimmed">
              {employeeCode ? employeeCode + " \u00b7 " : ""}
              {dateLabel}
            </Text>
          </Stack>

          <Group gap="xs">
            <Badge variant="light" color={colors.info}>
              {dayTypeLabel(day.data.segments[0]?.day_type)}
            </Badge>
            {day.data.status ? (
              <Badge variant="light">{day.data.status}</Badge>
            ) : (
              <Badge variant="light" color={colors.inactive}>
                {strings.attendance.dayPanel.noStatus}
              </Badge>
            )}
            {day.data.locked ? (
              <Badge color={colors.inactive}>{strings.attendance.dayPanel.locked}</Badge>
            ) : null}
            {reviewed ? (
              <Badge color={colors.info}>{strings.attendance.dayPanel.reviewed}</Badge>
            ) : (
              <Badge color={colors.pending}>Not reviewed</Badge>
            )}
            {day.data.flags.includes("overtime_pending_approval") ? (
              <Badge color={colors.pending}>
                {strings.attendance.dayPanel.overtime} pending
              </Badge>
            ) : null}
          </Group>

          <Divider />

          {day.data.shift_id ? (
            <Group gap="xs">
              <Text size="sm" c="dimmed">Shift:</Text>
              <Text size="sm" fw={500}>
                {(shifts.data ?? []).find((x) => x.id === day.data!.shift_id)?.name ??
                  day.data.shift_id.slice(0, 8)}
              </Text>
            </Group>
          ) : (
            <Text size="sm" c="dimmed">No shift assigned</Text>
          )}

          <Group gap="lg">
            <Stack gap={0}>
              <Text size="xs" c="dimmed">{strings.attendance.dayPanel.firstIn}</Text>
              <Text>
                {day.data.first_in
                  ? dayjs(day.data.first_in).format("HH:mm")
                  : "\u2014"}
              </Text>
            </Stack>
            <Stack gap={0}>
              <Text size="xs" c="dimmed">{strings.attendance.dayPanel.lastOut}</Text>
              <Text>
                {day.data.last_out
                  ? dayjs(day.data.last_out).format("HH:mm")
                  : "\u2014"}
              </Text>
            </Stack>
            <Stack gap={0}>
              <Text size="xs" c="dimmed">{strings.attendance.dayPanel.worked}</Text>
              <Text>
                {day.data.worked_minutes === null
                  ? "\u2014"
                  : `${day.data.worked_minutes} ${strings.attendance.dayPanel.minutes}`}
              </Text>
            </Stack>
            <Stack gap={0}>
              <Text size="xs" c="dimmed">{strings.attendance.dayPanel.overtime}</Text>
              <Text>
                {day.data.overtime_minutes === null
                  ? "\u2014"
                  : `${day.data.overtime_minutes} ${strings.attendance.dayPanel.minutes}`}
              </Text>
            </Stack>
          </Group>

          <Stack gap={4}>
            <Text size="sm" fw={500}>Rate breakdown</Text>
            {day.data.segments.length === 0 ? (
              <Text size="sm" c="dimmed">No segments computed.</Text>
            ) : (
              <Table striped withTableBorder>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Kind</Table.Th>
                    <Table.Th>Tier</Table.Th>
                    <Table.Th>Minutes</Table.Th>
                    <Table.Th>Rate</Table.Th>
                    <Table.Th>Value</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {day.data.segments.map((seg: SegmentOut) => (
                    <Table.Tr key={seg.id}>
                      <Table.Td>{seg.kind}</Table.Td>
                      <Table.Td>{seg.tier}</Table.Td>
                      <Table.Td>{seg.minutes}</Table.Td>
                      <Table.Td>{seg.rate_method}</Table.Td>
                      <Table.Td>{rateLabel(seg.rate_method, seg.rate_value)}</Table.Td>
                    </Table.Tr>
                  ))}
                  <Table.Tr>
                    <Table.Td colSpan={2}>
                      <Text size="sm" fw={600}>Total</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" fw={600}>
                        {day.data.segments.reduce((acc, x) => acc + x.minutes, 0)}
                      </Text>
                    </Table.Td>
                    <Table.Td colSpan={2} />
                  </Table.Tr>
                </Table.Tbody>
              </Table>
            )}
          </Stack>

          <Stack gap={4}>
            <Text size="sm" fw={500}>{strings.attendance.dayPanel.punches}</Text>
            {day.data.punches.length === 0 ? (
              <Text size="sm" c="dimmed">
                {strings.attendance.dayPanel.noPunches}
              </Text>
            ) : (
              <Table striped withTableBorder>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Time</Table.Th>
                    <Table.Th>Direction</Table.Th>
                    <Table.Th>Source</Table.Th>
                    <Table.Th>Confidence</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {day.data.punches.map((p) => (
                    <Table.Tr key={p.id}>
                      <Table.Td>{dayjs(p.punch_time).format("HH:mm:ss")}</Table.Td>
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
            <Text size="sm" fw={500}>{strings.attendance.dayPanel.exceptions}</Text>
            {exceptions.isLoading ? (
              <Loader size="xs" />
            ) : (exceptions.data ?? []).length === 0 ? (
              <Text size="sm" c="dimmed">{strings.attendance.dayPanel.noExceptions}</Text>
            ) : (
              <Stack gap={4}>
                {(exceptions.data ?? []).map((ex) => (
                  <Group key={ex.id} gap="xs" wrap="nowrap">
                    <Badge variant="light" color={ex.status === "open" ? colors.problem : colors.inactive}>
                      {ex.status}
                    </Badge>
                    <Text size="sm">{ex.type}</Text>
                    <Text size="sm" c="dimmed">{ex.message}</Text>
                  </Group>
                ))}
              </Stack>
            )}
          </Stack>

          <Divider />

          {!reviewed ? (
            <Button
              onClick={() => mark.mutate()}
              loading={mark.isPending}
              disabled={mark.isPending}
              data-testid="daypanel-mark-reviewed"
            >
              Mark reviewed
            </Button>
          ) : null}
          {mark.isError ? (
            <Alert color={colors.problem}>Mark reviewed failed.</Alert>
          ) : mark.isSuccess ? (
            <Alert color={colors.approved}>Marked reviewed.</Alert>
          ) : null}
        </Stack>
      )}
    </Drawer>
  );
}
