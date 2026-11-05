"""Job A fix: revert strings.ts, rewrite DayPanel with hardcoded English labels,
rewrite DayPanel.test.tsx with proper Request URL extraction."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

# ---------- 1. DayPanel.tsx (hardcoded labels, no new strings.ts keys) ----------
panel = SRC / "components" / "AttendanceSheet" / "DayPanel.tsx"
panel.write_text('''import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  if (method === "multiplier") return `\\u00d7 ${value}`;
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
            {employeeCode ? employeeCode + " \\u00b7 " : ""}
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
              {employeeName || "Loading employee\\u2026"}
            </Text>
            <Text size="sm" c="dimmed">
              {employeeCode ? employeeCode + " \\u00b7 " : ""}
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
                  : "\\u2014"}
              </Text>
            </Stack>
            <Stack gap={0}>
              <Text size="xs" c="dimmed">{strings.attendance.dayPanel.lastOut}</Text>
              <Text>
                {day.data.last_out
                  ? dayjs(day.data.last_out).format("HH:mm")
                  : "\\u2014"}
              </Text>
            </Stack>
            <Stack gap={0}>
              <Text size="xs" c="dimmed">{strings.attendance.dayPanel.worked}</Text>
              <Text>
                {day.data.worked_minutes === null
                  ? "\\u2014"
                  : `${day.data.worked_minutes} ${strings.attendance.dayPanel.minutes}`}
              </Text>
            </Stack>
            <Stack gap={0}>
              <Text size="xs" c="dimmed">{strings.attendance.dayPanel.overtime}</Text>
              <Text>
                {day.data.overtime_minutes === null
                  ? "\\u2014"
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
''', encoding="utf-8")
print("wrote DayPanel.tsx (hardcoded English labels)")

# ---------- 2. DayPanel.test.tsx (proper URL extraction) ----------
(panel.parent / "DayPanel.test.tsx").write_text('''import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { DayPanel } from "./DayPanel";

function jr(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  if (typeof Request !== "undefined" && input instanceof Request) return input.url;
  return String(input);
}

function renderPanel(overrides: { reviewedOverride?: boolean } = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <DayPanel
          employeeId="e1"
          workDate="2026-11-04"
          onClose={() => {}}
          reviewedOverride={overrides.reviewedOverride}
        />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("DayPanel", () => {
  it("renders employee name, status, and segment breakdown", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/attendance/day/")) {
        return jr({
          id: "d1", employee_id: "e1", work_date: "2026-11-04", status: "worked",
          first_in: "2026-11-04T06:00:00Z", last_out: "2026-11-04T15:00:00Z",
          worked_minutes: 540, normal_minutes: 480, overtime_minutes: 60, raw_minutes: 540,
          shift_id: "sh1", flags: [], source_version: 1, locked: false,
          row_version: 1, computed_at: "2026-11-05T06:00:00Z",
          site_timezone: "Africa/Johannesburg",
          segments: [
            { id: "sg1", attendance_day_id: "d1", local_date: "2026-11-04",
              day_type: "weekday", kind: "normal", tier: 1, minutes: 480,
              rate_method: "multiplier", rate_value: "1.0", overtime_status: null, source_refs: [] },
            { id: "sg2", attendance_day_id: "d1", local_date: "2026-11-04",
              day_type: "weekday", kind: "overtime", tier: 1, minutes: 60,
              rate_method: "multiplier", rate_value: "1.5", overtime_status: "approved", source_refs: [] },
          ],
        });
      }
      if (url.includes("/employees/e1")) {
        return jr({ id: "e1", first_name: "Thabo", last_name: "Mokoena", employee_code: "T001" });
      }
      if (url.includes("/attendance/exceptions")) {
        return jr({ items: [], next_cursor: null });
      }
      if (url.includes("/shifts")) {
        return jr({ items: [{ id: "sh1", name: "Day 08:00-17:00" }] });
      }
      return jr({});
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("Thabo Mokoena")).toBeInTheDocument(),
    );
    expect(screen.getByText(/T001/)).toBeInTheDocument();
    expect(screen.getByText("worked")).toBeInTheDocument();
    expect(screen.getByText("normal")).toBeInTheDocument();
    expect(screen.getByText("overtime")).toBeInTheDocument();
    expect(screen.getByText(/Day 08:00-17:00/)).toBeInTheDocument();
    expect(screen.getByText("Rate breakdown")).toBeInTheDocument();
    expect(screen.getByText("540")).toBeInTheDocument();
  });

  it("shows friendly 404 message when day does not exist", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/attendance/day/"))
        return jr({ error: { code: "record_not_found" } }, 404);
      if (url.includes("/employees/e1"))
        return jr({ id: "e1", first_name: "Nomsa", last_name: "Botha", employee_code: "T010" });
      if (url.includes("/attendance/exceptions"))
        return jr({ items: [], next_cursor: null });
      if (url.includes("/shifts")) return jr({ items: [] });
      return jr({});
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/No attendance record for this day/)).toBeInTheDocument(),
    );
    expect(screen.getByText("Nomsa Botha")).toBeInTheDocument();
  });

  it("renders exceptions list when present", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/attendance/day/")) {
        return jr({
          id: "d1", employee_id: "e1", work_date: "2026-11-04", status: "worked",
          first_in: "2026-11-04T06:00:00Z", last_out: "2026-11-04T15:00:00Z",
          worked_minutes: 540, normal_minutes: 480, overtime_minutes: 60, raw_minutes: 540,
          shift_id: null, flags: ["missing_out"], source_version: 1, locked: false,
          row_version: 1, computed_at: "2026-11-05T06:00:00Z",
          site_timezone: "Africa/Johannesburg", segments: [],
        });
      }
      if (url.includes("/employees/e1"))
        return jr({ id: "e1", first_name: "X", last_name: "Y", employee_code: "T001" });
      if (url.includes("/attendance/exceptions")) {
        return jr({ items: [{ id: "ex1", type: "missing_out", message: "No clock-out", status: "open" }], next_cursor: null });
      }
      if (url.includes("/shifts")) return jr({ items: [] });
      return jr({});
    });
    renderPanel();
    await waitFor(() => expect(screen.getByText("missing_out")).toBeInTheDocument());
    expect(screen.getByText("No clock-out")).toBeInTheDocument();
  });

  it("never renders an adjustment marker (hard rule)", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/attendance/day/")) {
        return jr({
          id: "d1", employee_id: "e1", work_date: "2026-11-04", status: "worked",
          first_in: "2026-11-04T06:00:00Z", last_out: "2026-11-04T15:00:00Z",
          worked_minutes: 540, normal_minutes: 480, overtime_minutes: 60, raw_minutes: 540,
          shift_id: null, flags: [], source_version: 1, locked: false,
          row_version: 1, computed_at: "2026-11-05T06:00:00Z",
          site_timezone: "Africa/Johannesburg", segments: [],
        });
      }
      if (url.includes("/employees/e1"))
        return jr({ id: "e1", first_name: "X", last_name: "Y", employee_code: "T001" });
      if (url.includes("/attendance/exceptions"))
        return jr({ items: [], next_cursor: null });
      if (url.includes("/shifts")) return jr({ items: [] });
      return jr({});
    });
    renderPanel();
    await waitFor(() => expect(screen.getByText("X Y")).toBeInTheDocument());
    expect(screen.queryByText(/adjusted/i)).not.toBeInTheDocument();
  });
});
''', encoding="utf-8")
print("wrote DayPanel.test.tsx (urlOf helper)")