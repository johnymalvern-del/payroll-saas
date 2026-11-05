"""P3: Day panel rebuild — segments table, shift name, exceptions, per-day mark-reviewed."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

# ---------- 1. api/attendance.ts: SegmentOut + fetchEmployeeById ----------
api = SRC / "api" / "attendance.ts"
s = api.read_text(encoding="utf-8")

if "export type SegmentOut" not in s:
    anchor = "export type DailyRow = {"
    seg_type = '''export type SegmentOut = {
  id: string;
  attendance_day_id: string;
  local_date: string;
  day_type: string;
  kind: string;
  tier: number;
  minutes: number;
  rate_method: string;
  rate_value: string;
  overtime_status: string | null;
  source_refs: unknown[];
};

'''
    s = s.replace(anchor, seg_type + anchor, 1)
    print("attendance.ts: SegmentOut type added")

if "segments: SegmentOut[]" not in s:
    m = re.search(r"(export type DayOut = \{[\s\S]*?)\n\};", s)
    if m:
        s = s[:m.end()-3] + "\n  segments: SegmentOut[];\n};" + s[m.end():]
        print("attendance.ts: segments added to DayOut")

if "segments: Array.isArray" not in s:
    anchor = "    exceptions: Array.isArray(obj.exceptions) ? (obj.exceptions as ExceptionRow[]) : [],\n"
    if anchor in s:
        s = s.replace(anchor, anchor + "    segments: Array.isArray(obj.segments) ? (obj.segments as SegmentOut[]) : [],\n", 1)
        print("attendance.ts: segments added to normaliseDayOut")

if "export async function fetchEmployeeById" not in s:
    anchor = "export async function fetchDay"
    helper = '''export async function fetchEmployeeById(
  id: string,
): Promise<{
  id: string;
  first_name: string;
  last_name: string;
  employee_code: string;
} | null> {
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/employees/${id}`), { credentials: "include" }),
  );
  if (!res.ok) return null;
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null;
  if (!data) return null;
  return {
    id: String(data.id ?? ""),
    first_name: String(data.first_name ?? ""),
    last_name: String(data.last_name ?? ""),
    employee_code: String(data.employee_code ?? ""),
  };
}

'''
    if anchor in s:
        s = s.replace(anchor, helper + anchor, 1)
        print("attendance.ts: fetchEmployeeById added")

api.write_text(s, encoding="utf-8")

# ---------- 2. api/attendance.ts: fetchExceptionsForDay ----------
s = api.read_text(encoding="utf-8")
if "export async function fetchExceptionsForDay" not in s:
    anchor = "export async function fetchDay"
    helper = '''export async function fetchExceptionsForDay(
  employeeId: string,
  workDate: string,
): Promise<ExceptionRow[]> {
  const qs = new URLSearchParams();
  qs.set("employee_id", employeeId);
  qs.set("from_date", workDate);
  qs.set("to_date", workDate);
  qs.set("limit", "100");
  const res = await wrappedFetch(
    new Request(absoluteUrl(`/api/v1/attendance/exceptions?${qs.toString()}`), {
      credentials: "include",
    }),
  );
  if (!res.ok) return [];
  const data = (await res.json().catch(() => null)) as { items?: unknown } | null;
  return Array.isArray(data?.items) ? (data!.items as ExceptionRow[]) : [];
}

'''
    if anchor in s:
        s = s.replace(anchor, helper + anchor, 1)
        api.write_text(s, encoding="utf-8")
        print("attendance.ts: fetchExceptionsForDay added")

# ---------- 3. strings.ts: dayPanel extensions ----------
st = SRC / "lib" / "strings.ts"
s = st.read_text(encoding="utf-8")
if "rateBreakdown:" not in s:
    # find dayPanel block, add keys before its closing brace
    m = re.search(r"(dayPanel:\s*\{[\s\S]*?)(\n  \},)", s)
    if not m:
        raise SystemExit("FATAL: dayPanel strings block not found")
    extras = '''
      dayType: "Day type",
      dayTypeWeekday: "Weekday",
      dayTypeSaturday: "Saturday",
      dayTypeSunday: "Sunday",
      dayTypeHoliday: "Public holiday",
      shift: "Shift",
      noShift: "No shift assigned",
      rateBreakdown: "Rate breakdown",
      rateKind: "Kind",
      rateTier: "Tier",
      rateMinutes: "Minutes",
      rateMethod: "Rate",
      rateValue: "Value",
      rateTotal: "Total",
      noSegments: "No segments computed.",
      notReviewed: "Not reviewed",
      markReviewed: "Mark reviewed",
      markReviewedSuccess: "Marked reviewed.",
      markReviewedFailed: "Mark reviewed failed.",
      noData: "No attendance record for this day.",
      loadingEmployee: "Loading employee\\u2026",
'''
    s = s[:m.end(1)] + extras + s[m.end(1):]
    st.write_text(s, encoding="utf-8")
    print("strings.ts: dayPanel extensions added")

# ---------- 4. DayPanel.tsx (full rewrite) ----------
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
  if (!dayType) return strings.attendance.dayPanel.dayTypeWeekday;
  const t = dayType.toLowerCase();
  if (t.includes("holiday")) return strings.attendance.dayPanel.dayTypeHoliday;
  if (t === "saturday") return strings.attendance.dayPanel.dayTypeSaturday;
  if (t === "sunday") return strings.attendance.dayPanel.dayTypeSunday;
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
            {strings.attendance.dayPanel.noData}
          </Alert>
        </Stack>
      ) : day.isError || !day.data ? (
        <Text c={colors.problem}>{strings.attendance.dayPanel.error}</Text>
      ) : (
        <Stack gap="md">
          <Stack gap={2}>
            <Text fw={600}>
              {employeeName || strings.attendance.dayPanel.loadingEmployee}
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
              <Badge color={colors.pending}>{strings.attendance.dayPanel.notReviewed}</Badge>
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
              <Text size="sm" c="dimmed">{strings.attendance.dayPanel.shift}:</Text>
              <Text size="sm" fw={500}>
                {(shifts.data ?? []).find((x) => x.id === day.data!.shift_id)?.name ??
                  day.data.shift_id.slice(0, 8)}
              </Text>
            </Group>
          ) : (
            <Text size="sm" c="dimmed">{strings.attendance.dayPanel.noShift}</Text>
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
            <Text size="sm" fw={500}>{strings.attendance.dayPanel.rateBreakdown}</Text>
            {day.data.segments.length === 0 ? (
              <Text size="sm" c="dimmed">{strings.attendance.dayPanel.noSegments}</Text>
            ) : (
              <Table striped withTableBorder>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{strings.attendance.dayPanel.rateKind}</Table.Th>
                    <Table.Th>{strings.attendance.dayPanel.rateTier}</Table.Th>
                    <Table.Th>{strings.attendance.dayPanel.rateMinutes}</Table.Th>
                    <Table.Th>{strings.attendance.dayPanel.rateMethod}</Table.Th>
                    <Table.Th>{strings.attendance.dayPanel.rateValue}</Table.Th>
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
                      <Text size="sm" fw={600}>{strings.attendance.dayPanel.rateTotal}</Text>
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
              {strings.attendance.dayPanel.markReviewed}
            </Button>
          ) : null}
          {mark.isError ? (
            <Alert color={colors.problem}>
              {strings.attendance.dayPanel.markReviewedFailed}
            </Alert>
          ) : mark.isSuccess ? (
            <Alert color={colors.approved}>
              {strings.attendance.dayPanel.markReviewedSuccess}
            </Alert>
          ) : null}
        </Stack>
      )}
    </Drawer>
  );
}
''', encoding="utf-8")
print("wrote DayPanel.tsx")

# ---------- 5. DayPanel.test.tsx ----------
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

function renderPanel(overrides: { reviewedOverride?: boolean } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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
      const url = String(input);
      if (url.includes("/attendance/day/")) {
        return jr({
          id: "d1",
          employee_id: "e1",
          work_date: "2026-11-04",
          status: "worked",
          first_in: "2026-11-04T06:00:00Z",
          last_out: "2026-11-04T15:00:00Z",
          worked_minutes: 540,
          normal_minutes: 480,
          overtime_minutes: 60,
          raw_minutes: 540,
          shift_id: "sh1",
          flags: [],
          source_version: 1,
          locked: false,
          row_version: 1,
          computed_at: "2026-11-05T06:00:00Z",
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
  });

  it("shows friendly message when day does not exist (404)", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/attendance/day/")) return jr({ error: { code: "record_not_found" } }, 404);
      if (url.includes("/employees/e1")) return jr({ id: "e1", first_name: "Nomsa", last_name: "Botha", employee_code: "T010" });
      if (url.includes("/attendance/exceptions")) return jr({ items: [], next_cursor: null });
      if (url.includes("/shifts")) return jr({ items: [] });
      return jr({});
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/No attendance record for this day/)).toBeInTheDocument(),
    );
  });

  it("renders exceptions list when present", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
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
      if (url.includes("/employees/e1")) return jr({ id: "e1", first_name: "X", last_name: "Y", employee_code: "T001" });
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

  it("does not render any 'adjusted' marker (hard rule)", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
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
      if (url.includes("/employees/e1")) return jr({ id: "e1", first_name: "X", last_name: "Y", employee_code: "T001" });
      if (url.includes("/attendance/exceptions")) return jr({ items: [], next_cursor: null });
      if (url.includes("/shifts")) return jr({ items: [] });
      return jr({});
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("X Y")).toBeInTheDocument(),
    );
    expect(screen.queryByText(/adjusted/i)).not.toBeInTheDocument();
  });
});
''', encoding="utf-8")
print("wrote DayPanel.test.tsx")

print("\nP3 files written. Note: AttendanceSheetPage is unchanged; DayPanel")
print("fetches its own employee + shift + exceptions data. No parent patch needed.")