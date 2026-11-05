import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Button,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import {
  fetchBranches,
  fetchDaily,
  fetchDepartments,
  fetchSheet,
  fetchSites,
} from "../api/attendance";
import { DailyList } from "../components/AttendanceSheet/DailyList";
import { DayPanel } from "../components/AttendanceSheet/DayPanel";
import { FilterBar } from "../components/AttendanceSheet/FilterBar";
import { MarkReviewedModal } from "../components/AttendanceSheet/MarkReviewedModal";
import { MonthlyGrid } from "../components/AttendanceSheet/MonthlyGrid";
import { strings } from "../lib/strings";
import { toCsv, downloadCsv } from "../lib/csv";

const PAGE_SIZE = 50;
type View = "monthly" | "daily";

export function AttendanceSheetPage() {
  const [view, setView] = useState<View>("monthly");
  const [fromDate, setFromDate] = useState<Date | null>(
    dayjs().startOf("month").toDate(),
  );
  const [toDate, setToDate] = useState<Date | null>(
    dayjs().endOf("month").toDate(),
  );
  const [dailyDate, setDailyDate] = useState<Date | null>(dayjs().toDate());
  const [branchId, setBranchId] = useState<string | null>(null);
  const [siteId, setSiteId] = useState<string | null>(null);
  const [departmentId, setDepartmentId] = useState<string | null>(null);
  const [attendanceStatus, setAttendanceStatus] = useState<string[]>([]);
  const [includeTerminated, setIncludeTerminated] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selectedDay, setSelectedDay] = useState<{ employeeId: string; workDate: string } | null>(null);
  const [markOpen, setMarkOpen] = useState(false);

  const fromStr = useMemo(
    () => (fromDate ? dayjs(fromDate).format("YYYY-MM-DD") : ""),
    [fromDate],
  );
  const toStr = useMemo(
    () => (toDate ? dayjs(toDate).format("YYYY-MM-DD") : ""),
    [toDate],
  );
  const dailyStr = useMemo(
    () => (dailyDate ? dayjs(dailyDate).format("YYYY-MM-DD") : ""),
    [dailyDate],
  );
  const rangeOk = useMemo(() => {
    if (!fromDate || !toDate) return false;
    const diff = dayjs(toDate).diff(dayjs(fromDate), "day");
    return diff >= 0 && diff <= 30;
  }, [fromDate, toDate]);

  const branches = useQuery({ queryKey: ["refs", "branches"], queryFn: fetchBranches });
  const sites = useQuery({ queryKey: ["refs", "sites"], queryFn: fetchSites });
  const departments = useQuery({ queryKey: ["refs", "departments"], queryFn: fetchDepartments });

  const sheet = useQuery({
    queryKey: ["attendance", "sheet", fromStr, toStr, branchId, siteId, departmentId, includeTerminated, cursor],
    queryFn: () =>
      fetchSheet({ fromDate: fromStr, toDate: toStr, branchId, siteId, departmentId, includeTerminated, limit: PAGE_SIZE, cursor }),
    enabled: view === "monthly" && rangeOk,
  });

  const daily = useQuery({
    queryKey: ["attendance", "daily", dailyStr, branchId, siteId, departmentId, includeTerminated, cursor],
    queryFn: () =>
      fetchDaily({ date: dailyStr, branchId, siteId, departmentId, includeTerminated, limit: PAGE_SIZE, cursor }),
    enabled: view === "daily" && !!dailyStr,
  });

  const onReset = () => {
    setFromDate(dayjs().startOf("month").toDate());
    setToDate(dayjs().endOf("month").toDate());
    setDailyDate(dayjs().toDate());
    setBranchId(null);
    setSiteId(null);
    setDepartmentId(null);
    setAttendanceStatus([]);
    setIncludeTerminated(false);
    setCursor(null);
  };

  const openDay = (employeeId: string, workDate: string) => {
    setSelectedDay({ employeeId, workDate });
  };

  const exportCsv = () => {
    const data = sheet.data;
    if (!data || data.items.length === 0) return;
    const headers = [
      "employee_code",
      "employee_name",
      "work_date",
      "status",
      "worked_minutes",
      "normal_minutes",
      "overtime_minutes",
      "flags",
      "open_exception_count",
      "locked",
      "reviewed",
    ];
    const rows: string[][] = [headers];
    for (const emp of data.items) {
      for (const d of emp.days) {
        rows.push([
          emp.employee_code,
          emp.employee_name,
          d.work_date,
          d.status ?? "",
          d.worked_minutes == null ? "" : String(d.worked_minutes),
          d.normal_minutes == null ? "" : String(d.normal_minutes),
          d.overtime_minutes == null ? "" : String(d.overtime_minutes),
          (d.flags ?? []).join(";"),
          String(d.open_exception_count),
          d.locked ? "true" : "false",
          d.reviewed ? "true" : "false",
        ]);
      }
    }
    const csv = toCsv(rows);
    const month = fromDate
      ? dayjs(fromDate).format("YYYY-MM")
      : dayjs().format("YYYY-MM");
    downloadCsv(`attendance-sheet-${month}.csv`, csv);
  };

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>{strings.attendance.title}</Title>
        <Button
          variant="default"
          disabled={!sheet.data || sheet.data.items.length === 0}
          onClick={exportCsv}
          data-testid="attendance-export-csv"
        >
          Export CSV
        </Button>
        <SegmentedControl
          value={view}
          onChange={(v) => {
            setView(v as View);
            setCursor(null);
          }}
          data={[
            { label: strings.attendance.viewMonthly, value: "monthly" },
            { label: strings.attendance.viewDaily, value: "daily" },
          ]}
        />
      </Group>

      <Paper withBorder p="md">
        <FilterBar
          fromDate={fromDate}
          toDate={toDate}
          branchId={branchId}
          siteId={siteId}
          departmentId={departmentId}
          attendanceStatus={attendanceStatus}
          includeTerminated={includeTerminated}
          branches={branches.data ?? []}
          sites={sites.data ?? []}
          departments={departments.data ?? []}
          onFromDate={(d) => { setFromDate(d); setCursor(null); }}
          onToDate={(d) => { setToDate(d); setCursor(null); }}
          onBranch={(v) => { setBranchId(v); setCursor(null); }}
          onSite={(v) => { setSiteId(v); setCursor(null); }}
          onDepartment={(v) => { setDepartmentId(v); setCursor(null); }}
          onAttendanceStatus={setAttendanceStatus}
          onIncludeTerminated={(v) => { setIncludeTerminated(v); setCursor(null); }}
          onReset={onReset}
        />
        {view === "monthly" && !rangeOk ? (
          <Text c="red" size="sm" mt="sm">
            {strings.attendance.rangeTooWide}
          </Text>
        ) : null}
      </Paper>

      <Paper withBorder p="md">
        {view === "monthly" ? (
          sheet.isLoading ? (
            <Group justify="center" p="xl"><Loader /></Group>
          ) : sheet.isError ? (
            <Text c="red">{strings.attendance.error}</Text>
          ) : (
            <MonthlyGrid
              fromDate={fromStr}
              toDate={toStr}
              employees={sheet.data?.items ?? []}
              attendanceStatus={attendanceStatus}
              onCellClick={openDay}
            />
          )
        ) : daily.isLoading ? (
          <Group justify="center" p="xl"><Loader /></Group>
        ) : daily.isError ? (
          <Text c="red">{strings.attendance.dailyError}</Text>
        ) : (
          <DailyList
            rows={daily.data?.items ?? []}
            onRowClick={(empId, date) => openDay(empId, date)}
          />
        )}
      </Paper>

      <Group justify="space-between" wrap="wrap">
        <Button variant="default" onClick={() => setMarkOpen(true)} disabled={view !== "monthly" || !rangeOk}>
          {strings.attendance.markReviewed.submit}
        </Button>
        <Group gap="sm">
          <Button variant="default" disabled={!cursor} onClick={() => setCursor(null)}>
            {strings.attendance.firstPage}
          </Button>
          <Button
            variant="default"
            disabled={view === "monthly" ? !sheet.data?.next_cursor : !daily.data?.next_cursor}
            onClick={() => {
              const nextCursor = view === "monthly" ? sheet.data?.next_cursor : daily.data?.next_cursor;
              setCursor(nextCursor ?? null);
            }}
          >
            {strings.attendance.nextPage}
          </Button>
        </Group>
      </Group>

      {view === "daily" ? (
        <Paper withBorder p="md">
          <Group gap="sm" align="end">
            <label>
              <Text size="sm" fw={500}>{strings.attendance.dailyDate}</Text>
              <input
                type="date"
                value={dailyStr}
                onChange={(e) => {
                  const v = e.currentTarget.value;
                  setDailyDate(v ? new Date(v) : null);
                  setCursor(null);
                }}
              />
            </label>
          </Group>
        </Paper>
      ) : null}

      {selectedDay ? (
        <DayPanel
          employeeId={selectedDay.employeeId}
          workDate={selectedDay.workDate}
          onClose={() => setSelectedDay(null)}
        />
      ) : null}

      <MarkReviewedModal
        opened={markOpen}
        fromDate={fromStr}
        toDate={toStr}
        siteId={siteId}
        branchId={branchId}
        departmentId={departmentId}
        includeTerminated={includeTerminated}
        onClose={() => setMarkOpen(false)}
      />
    </Stack>
  );
}
