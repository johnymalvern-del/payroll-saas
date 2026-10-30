import { Button, Group, MultiSelect, Select, Switch, TextInput } from "@mantine/core";
import dayjs from "dayjs";
import type { Ref } from "../../api/attendance";
import { strings } from "../../lib/strings";

type Props = {
  fromDate: Date | null;
  toDate: Date | null;
  branchId: string | null;
  siteId: string | null;
  departmentId: string | null;
  attendanceStatus: string[];
  includeTerminated: boolean;
  branches: Ref[];
  sites: Ref[];
  departments: Ref[];
  onFromDate: (d: Date | null) => void;
  onToDate: (d: Date | null) => void;
  onBranch: (v: string | null) => void;
  onSite: (v: string | null) => void;
  onDepartment: (v: string | null) => void;
  onAttendanceStatus: (v: string[]) => void;
  onIncludeTerminated: (v: boolean) => void;
  onReset: () => void;
};

export function FilterBar(props: Props) {
  const branchOpts = props.branches.map((b) => ({ value: b.id, label: b.name }));
  const siteOpts = props.sites.map((s) => ({ value: s.id, label: s.name }));
  const deptOpts = props.departments.map((d) => ({ value: d.id, label: d.name }));
  const statusOpts = ["worked", "leave", "sick", "absent", "day_off"].map((s) => ({
    value: s,
    label: s.replace("_", " "),
  }));

  const fromValue = props.fromDate ? dayjs(props.fromDate).format("YYYY-MM-DD") : "";
  const toValue = props.toDate ? dayjs(props.toDate).format("YYYY-MM-DD") : "";

  return (
    <Group gap="sm" wrap="wrap" align="end">
      <TextInput
        label={strings.attendance.fromDate}
        type="date"
        value={fromValue}
        onChange={(e) => {
          const v = e.currentTarget.value;
          props.onFromDate(v ? new Date(v) : null);
        }}
      />
      <TextInput
        label={strings.attendance.toDate}
        type="date"
        value={toValue}
        onChange={(e) => {
          const v = e.currentTarget.value;
          props.onToDate(v ? new Date(v) : null);
        }}
      />
      <Select
        label={strings.attendance.branch}
        data={[{ value: "", label: strings.attendance.all }, ...branchOpts]}
        value={props.branchId ?? ""}
        onChange={(v) => props.onBranch(v || null)}
        allowDeselect={false}
      />
      <Select
        label={strings.attendance.site}
        data={[{ value: "", label: strings.attendance.all }, ...siteOpts]}
        value={props.siteId ?? ""}
        onChange={(v) => props.onSite(v || null)}
        allowDeselect={false}
      />
      <Select
        label={strings.attendance.department}
        data={[{ value: "", label: strings.attendance.all }, ...deptOpts]}
        value={props.departmentId ?? ""}
        onChange={(v) => props.onDepartment(v || null)}
        allowDeselect={false}
      />
      <MultiSelect
        label={strings.attendance.attendanceStatus}
        data={statusOpts}
        value={props.attendanceStatus}
        onChange={props.onAttendanceStatus}
        placeholder={strings.attendance.allStatuses}
        clearable
      />
      <Switch
        label={strings.attendance.includeTerminated}
        checked={props.includeTerminated}
        onChange={(e) => props.onIncludeTerminated(e.currentTarget.checked)}
      />
      <Button variant="default" onClick={props.onReset}>
        {strings.attendance.reset}
      </Button>
    </Group>
  );
}
