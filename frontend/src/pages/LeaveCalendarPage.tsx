import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert, Badge, Button, Card, Drawer, Group, Loader, Stack, Text, Title,
} from "@mantine/core";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import { useMe } from "../auth/useMe";
import {
  fetchLeaveRequests,
  type LeaveRequestOut,
} from "../api/leaveRequests";

/**
 * The backend date filter is (from_date >= X AND to_date <= Y), not an
 * overlap check. Fetching a ±180-day window around the visible month
 * catches every leave that ends within 180 days after or starts within
 * 180 days before the visible month. Leaves longer than 180 days may not
 * appear in the first or last month of their span; this is documented in
 * the page description.
 */
const WINDOW_DAYS = 180;

const WEEKDAY_HEADERS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function employeeColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  const hue = Math.abs(h) % 360;
  return `hsl(${hue} 65% 82%)`;
}

function employeeShortName(r: LeaveRequestOut): string {
  if (r.employee_name) {
    const parts = r.employee_name.trim().split(/\s+/);
    return parts[0] || r.employee_name;
  }
  if (r.employee_code) return r.employee_code;
  return "—";
}

function expandToCalendarDays(r: LeaveRequestOut): Dayjs[] {
  const out: Dayjs[] = [];
  let cur = dayjs(r.from_date);
  const end = dayjs(r.to_date);
  while (!cur.isAfter(end, "day")) {
    out.push(cur);
    cur = cur.add(1, "day");
  }
  return out;
}

export function LeaveCalendarPage() {
  const me = useMe();
  const permissions = me.data?.permissions ?? [];
  const canView = permissions.includes("leave_approve");

  const [currentMonth, setCurrentMonth] = useState<Dayjs>(() =>
    dayjs().startOf("month"),
  );
  const [selectedDay, setSelectedDay] = useState<Dayjs | null>(null);

  const monthStart = currentMonth.startOf("month");
  const monthEnd = currentMonth.endOf("month");
  const windowFrom = monthStart.subtract(WINDOW_DAYS, "day").format("YYYY-MM-DD");
  const windowTo = monthEnd.add(WINDOW_DAYS, "day").format("YYYY-MM-DD");

  const q = useQuery({
    queryKey: ["leave_calendar", monthStart.format("YYYY-MM")],
    queryFn: () =>
      fetchLeaveRequests({
        status: "approved",
        from_date_gte: windowFrom,
        to_date_lte: windowTo,
        limit: 500,
      }),
    enabled: canView,
  });

  const leaveByDay = useMemo(() => {
    const map = new Map<string, LeaveRequestOut[]>();
    const rows = q.data?.items ?? [];
    for (const r of rows) {
      const days = expandToCalendarDays(r);
      for (const d of days) {
        const key = d.format("YYYY-MM-DD");
        if (!map.has(key)) map.set(key, []);
        map.get(key)!.push(r);
      }
    }
    return map;
  }, [q.data]);

  const gridDays = useMemo(() => {
    const firstWeekdayIdx = (monthStart.day() + 6) % 7; // 0=Mon, 6=Sun
    const daysInMonth = monthEnd.date();
    const cells: Array<{ day: Dayjs | null }> = [];
    for (let i = 0; i < firstWeekdayIdx; i++) cells.push({ day: null });
    for (let i = 0; i < daysInMonth; i++) {
      cells.push({ day: monthStart.add(i, "day") });
    }
    while (cells.length % 7 !== 0) cells.push({ day: null });
    return cells;
  }, [monthStart, monthEnd]);

  const todayStr = dayjs().format("YYYY-MM-DD");

  if (me.isLoading) {
    return <Loader data-testid="leave-calendar-loading" />;
  }
  if (!canView) {
    return (
      <Alert color="yellow" data-testid="leave-calendar-no-permission">
        You do not have permission to view the leave calendar.
      </Alert>
    );
  }

  const selectedLeave = selectedDay
    ? leaveByDay.get(selectedDay.format("YYYY-MM-DD")) ?? []
    : [];

  return (
    <Stack gap="md" data-testid="leave-calendar-page">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Leave Calendar</Title>
          <Text size="sm" c="dimmed">
            Approved leave across employees you can see.
          </Text>
        </div>
        <Group gap="xs">
          <Button
            variant="default"
            data-testid="cal-prev"
            onClick={() => setCurrentMonth(currentMonth.subtract(1, "month"))}
          >
            ←
          </Button>
          <Button
            variant="default"
            data-testid="cal-today"
            onClick={() => setCurrentMonth(dayjs().startOf("month"))}
          >
            Today
          </Button>
          <Button
            variant="default"
            data-testid="cal-next"
            onClick={() => setCurrentMonth(currentMonth.add(1, "month"))}
          >
            →
          </Button>
        </Group>
      </Group>

      <Text size="lg" fw={600} data-testid="cal-month-label">
        {monthStart.format("MMMM YYYY")}
      </Text>

      {q.isLoading && <Loader data-testid="cal-loading" />}
      {q.isError && (
        <Alert color="red" data-testid="cal-error">
          Could not load leave calendar.
        </Alert>
      )}

      {q.isSuccess && q.data?.next_cursor && (
        <Alert color="orange" data-testid="cal-truncated">
          More than 500 approved requests in this window; showing first 500.
        </Alert>
      )}

      <Card withBorder padding="md">
        <div
          data-testid="cal-grid"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(7, minmax(0, 1fr))",
            gap: 4,
          }}
        >
          {WEEKDAY_HEADERS.map((w) => (
            <div
              key={w}
              style={{ textAlign: "center", fontWeight: 600, padding: 8 }}
            >
              {w}
            </div>
          ))}
          {gridDays.map((cell, i) => {
            if (cell.day === null) {
              return <div key={`pad-${i}`} style={{ minHeight: 90 }} />;
            }
            const dateStr = cell.day.format("YYYY-MM-DD");
            const leaves = leaveByDay.get(dateStr) ?? [];
            const isToday = dateStr === todayStr;
            return (
              <div
                key={dateStr}
                data-testid={`cal-cell-${dateStr}`}
                onClick={() => setSelectedDay(cell.day)}
                style={{
                  minHeight: 90,
                  padding: 6,
                  border: isToday
                    ? "2px solid var(--mantine-color-blue-5)"
                    : "1px solid var(--mantine-color-gray-3)",
                  borderRadius: 4,
                  cursor: "pointer",
                  background: "white",
                }}
              >
                <Text size="xs" fw={600} mb={4}>
                  {cell.day.date()}
                </Text>
                {leaves.slice(0, 3).map((r) => (
                  <div
                    key={r.id}
                    data-testid={`cal-chip-${r.id}`}
                    title={`${employeeShortName(r)} — ${r.leave_type_name ?? "Leave"}`}
                    style={{
                      background: employeeColor(r.employee_id),
                      padding: "2px 6px",
                      borderRadius: 4,
                      fontSize: 11,
                      marginBottom: 2,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {employeeShortName(r)}
                  </div>
                ))}
                {leaves.length > 3 && (
                  <Text size="xs" c="dimmed">
                    +{leaves.length - 3} more
                  </Text>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      <Drawer
        opened={selectedDay !== null}
        onClose={() => setSelectedDay(null)}
        position="right"
        title={
          selectedDay
            ? selectedDay.format("dddd, DD MMMM YYYY")
            : "Leave details"
        }
      >
        <Stack gap="sm" data-testid="cal-day-drawer-content">
          {selectedLeave.length === 0 && (
            <Text c="dimmed" data-testid="cal-day-drawer-empty">
              No approved leave on this day.
            </Text>
          )}
          {selectedLeave.map((r) => (
            <Card
              key={r.id}
              withBorder
              padding="sm"
              data-testid={`cal-detail-${r.id}`}
            >
              <Stack gap={2}>
                <Text fw={600}>
                  {r.employee_name ?? r.employee_code ?? "—"}
                </Text>
                <Text size="sm">{r.leave_type_name ?? "Leave"}</Text>
                <Text size="xs" c="dimmed">
                  {r.from_date} → {r.to_date}
                </Text>
                <Badge size="sm" color="green" variant="light">
                  {r.status}
                </Badge>
              </Stack>
            </Card>
          ))}
        </Stack>
      </Drawer>
    </Stack>
  );
}