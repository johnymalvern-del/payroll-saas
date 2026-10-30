import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Button,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import {
  fetchBranches,
  fetchDepartments,
  fetchSheet,
  fetchSites,
} from "../api/attendance";
import { FilterBar } from "../components/AttendanceSheet/FilterBar";
import { MonthlyGrid } from "../components/AttendanceSheet/MonthlyGrid";
import { strings } from "../lib/strings";

const PAGE_SIZE = 50;

export function AttendanceSheetPage() {
  const [fromDate, setFromDate] = useState<Date | null>(
    dayjs().startOf("month").toDate(),
  );
  const [toDate, setToDate] = useState<Date | null>(
    dayjs().endOf("month").toDate(),
  );
  const [branchId, setBranchId] = useState<string | null>(null);
  const [siteId, setSiteId] = useState<string | null>(null);
  const [departmentId, setDepartmentId] = useState<string | null>(null);
  const [attendanceStatus, setAttendanceStatus] = useState<string[]>([]);
  const [includeTerminated, setIncludeTerminated] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);

  const fromStr = useMemo(
    () => (fromDate ? dayjs(fromDate).format("YYYY-MM-DD") : ""),
    [fromDate],
  );
  const toStr = useMemo(
    () => (toDate ? dayjs(toDate).format("YYYY-MM-DD") : ""),
    [toDate],
  );
  const rangeOk = useMemo(() => {
    if (!fromDate || !toDate) return false;
    const diff = dayjs(toDate).diff(dayjs(fromDate), "day");
    return diff >= 0 && diff <= 30;
  }, [fromDate, toDate]);

  const branches = useQuery({
    queryKey: ["refs", "branches"],
    queryFn: fetchBranches,
  });
  const sites = useQuery({
    queryKey: ["refs", "sites"],
    queryFn: fetchSites,
  });
  const departments = useQuery({
    queryKey: ["refs", "departments"],
    queryFn: fetchDepartments,
  });

  const sheet = useQuery({
    queryKey: [
      "attendance",
      "sheet",
      fromStr,
      toStr,
      branchId,
      siteId,
      departmentId,
      includeTerminated,
      cursor,
    ],
    queryFn: () =>
      fetchSheet({
        fromDate: fromStr,
        toDate: toStr,
        branchId,
        siteId,
        departmentId,
        includeTerminated,
        limit: PAGE_SIZE,
        cursor,
      }),
    enabled: rangeOk,
  });

  const onReset = () => {
    setFromDate(dayjs().startOf("month").toDate());
    setToDate(dayjs().endOf("month").toDate());
    setBranchId(null);
    setSiteId(null);
    setDepartmentId(null);
    setAttendanceStatus([]);
    setIncludeTerminated(false);
    setCursor(null);
  };

  return (
    <Stack gap="md">
      <Title order={2}>{strings.attendance.title}</Title>
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
          onFromDate={(d) => {
            setFromDate(d);
            setCursor(null);
          }}
          onToDate={(d) => {
            setToDate(d);
            setCursor(null);
          }}
          onBranch={(v) => {
            setBranchId(v);
            setCursor(null);
          }}
          onSite={(v) => {
            setSiteId(v);
            setCursor(null);
          }}
          onDepartment={(v) => {
            setDepartmentId(v);
            setCursor(null);
          }}
          onAttendanceStatus={setAttendanceStatus}
          onIncludeTerminated={(v) => {
            setIncludeTerminated(v);
            setCursor(null);
          }}
          onReset={onReset}
        />
        {!rangeOk ? (
          <Text c="red" size="sm" mt="sm">
            {strings.attendance.rangeTooWide}
          </Text>
        ) : null}
      </Paper>
      <Paper withBorder p="md">
        {sheet.isLoading ? (
          <Group justify="center" p="xl">
            <Loader />
          </Group>
        ) : sheet.isError ? (
          <Text c="red">{strings.attendance.error}</Text>
        ) : (
          <MonthlyGrid
            fromDate={fromStr}
            toDate={toStr}
            employees={sheet.data?.items ?? []}
            attendanceStatus={attendanceStatus}
          />
        )}
      </Paper>
      <Group justify="space-between">
        <Button
          variant="default"
          disabled={!cursor}
          onClick={() => setCursor(null)}
        >
          {strings.attendance.firstPage}
        </Button>
        <Button
          variant="default"
          disabled={!sheet.data?.next_cursor}
          onClick={() => setCursor(sheet.data?.next_cursor ?? null)}
        >
          {strings.attendance.nextPage}
        </Button>
      </Group>
    </Stack>
  );
}
