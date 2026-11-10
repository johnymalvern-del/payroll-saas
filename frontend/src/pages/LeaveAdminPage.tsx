import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  Alert, Badge, Button, Group, Loader, SegmentedControl, Select, Stack,
  Table, Text, TextInput, Title,
} from "@mantine/core";
import dayjs from "dayjs";
import { useMe } from "../auth/useMe";
import { fetchLeaveTypes, type LeaveTypeOut } from "../api/leaveTypes";
import { fetchLeaveRequests, type LeaveRequestOut } from "../api/leaveRequests";
import { fetchEmployeesPage, type EmployeeOut } from "../api/employees";
import { branchesApi } from "../api/branches";

const PAGE_SIZE = 100;

const STATUS_OPTIONS = [
  { label: "All", value: "all" },
  { label: "Draft", value: "draft" },
  { label: "Submitted", value: "submitted" },
  { label: "Approved", value: "approved" },
  { label: "Rejected", value: "rejected" },
  { label: "Cancelled", value: "cancelled" },
];

function fmt(s: string): string {
  const n = Number(s);
  return Number.isFinite(n) ? n.toFixed(2) : s;
}

function statusColor(s: string): string {
  switch (s) {
    case "approved": return "green";
    case "rejected": return "red";
    case "submitted": return "blue";
    case "cancelled": return "gray";
    default: return "gray";
  }
}

export function LeaveAdminPage() {
  const me = useMe();
  const navigate = useNavigate();

  const [statusFilter, setStatusFilter] = useState("all");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [employeeFilter, setEmployeeFilter] = useState<string | null>(null);
  const [branchFilter, setBranchFilter] = useState<string | null>(null);
  const [leaveTypeFilter, setLeaveTypeFilter] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");

  const hasEmployeeCrud =
    me.data?.permissions?.includes("employee_crud") ?? false;

  const employeesQuery = useQuery({
    queryKey: ["refs", "employees_full"],
    queryFn: () =>
      fetchEmployeesPage({ limit: 500, include_terminated: true }),
    staleTime: 5 * 60 * 1000,
    enabled: hasEmployeeCrud,
  });

  const branchesQuery = useQuery({
    queryKey: ["refs", "branches"],
    queryFn: () => branchesApi.list(),
    staleTime: 5 * 60 * 1000,
    enabled: hasEmployeeCrud,
  });

  const leaveTypesQuery = useQuery({
    queryKey: ["leave_types"],
    queryFn: fetchLeaveTypes,
    staleTime: 5 * 60 * 1000,
    enabled: hasEmployeeCrud,
  });

  const requests = useInfiniteQuery({
    queryKey: [
      "leave_requests",
      "admin",
      statusFilter,
      fromDate,
      toDate,
      employeeFilter,
    ],
    queryFn: ({ pageParam }) =>
      fetchLeaveRequests({
        status: statusFilter === "all" ? undefined : statusFilter,
        from_date_gte: fromDate || undefined,
        to_date_lte: toDate || undefined,
        employee_id: employeeFilter || undefined,
        limit: PAGE_SIZE,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: hasEmployeeCrud,
  });

  const employeeMap = useMemo(() => {
    const map = new Map<
      string,
      { name: string; code: string; branch_id: string | null }
    >();
    for (const e of employeesQuery.data?.items ?? []) {
      map.set(e.id, {
        name: `${e.first_name} ${e.last_name}`.trim(),
        code: e.employee_code,
        branch_id: e.branch_id,
      });
    }
    return map;
  }, [employeesQuery.data]);

  const branchNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const b of branchesQuery.data?.items ?? []) {
      map.set(b.id, b.name);
    }
    return map;
  }, [branchesQuery.data]);

  const typeNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of leaveTypesQuery.data?.items ?? []) {
      map.set(t.id, t.name);
    }
    return map;
  }, [leaveTypesQuery.data]);

  const employeeOptions = useMemo(
    () =>
      (employeesQuery.data?.items ?? [])
        .filter((e: EmployeeOut) => e.status !== "terminated")
        .map((e) => ({
          value: e.id,
          label: `${e.employee_code} — ${e.first_name} ${e.last_name}`,
        })),
    [employeesQuery.data],
  );

  const branchOptions = useMemo(
    () =>
      (branchesQuery.data?.items ?? []).map((b) => ({
        value: b.id,
        label: b.name,
      })),
    [branchesQuery.data],
  );

  const leaveTypeOptions = useMemo(
    () =>
      (leaveTypesQuery.data?.items ?? []).map((t: LeaveTypeOut) => ({
        value: t.id,
        label: t.name,
      })),
    [leaveTypesQuery.data],
  );

  const rawItems: LeaveRequestOut[] =
    requests.data?.pages.flatMap((p) => p.items) ?? [];

  const items = rawItems.filter((r) => {
    const emp = employeeMap.get(r.employee_id);
    if (branchFilter && emp?.branch_id !== branchFilter) return false;
    if (leaveTypeFilter && r.leave_type_id !== leaveTypeFilter) return false;
    if (searchTerm.trim()) {
      const q = searchTerm.trim().toLowerCase();
      if (!emp) return false;
      if (
        !emp.name.toLowerCase().includes(q) &&
        !emp.code.toLowerCase().includes(q)
      ) {
        return false;
      }
    }
    return true;
  });

  if (me.isLoading) {
    return <Loader data-testid="leave-admin-loading" />;
  }
  if (!hasEmployeeCrud) {
    return (
      <Alert color="yellow" data-testid="leave-admin-no-permission">
        You do not have permission to view the leave admin list. The Leave
        Admin module requires the employee management permission.
      </Alert>
    );
  }

  return (
    <Stack gap="md" data-testid="leave-admin-page">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Leave Admin</Title>
          <Text size="sm" c="dimmed">
            All leave applications across employees you are authorised to see.
          </Text>
        </div>
        <Button
          variant="default"
          component={Link}
          to="/leave"
          data-testid="leave-admin-my-leave-link"
        >
          My Leave
        </Button>
      </Group>

      <Group gap="sm">
        <SegmentedControl
          value={statusFilter}
          onChange={setStatusFilter}
          data={STATUS_OPTIONS}
          data-testid="leave-admin-status-filter"
        />
      </Group>

      <Group gap="sm" align="flex-end">
        <TextInput
          type="date"
          label="From date"
          value={fromDate}
          onChange={(e) => setFromDate(e.currentTarget.value)}
          data-testid="leave-admin-from-date"
          style={{ width: 180 }}
        />
        <TextInput
          type="date"
          label="To date"
          value={toDate}
          onChange={(e) => setToDate(e.currentTarget.value)}
          data-testid="leave-admin-to-date"
          style={{ width: 180 }}
        />
        <Select
          label="Employee"
          data={employeeOptions}
          value={employeeFilter}
          onChange={setEmployeeFilter}
          searchable
          clearable
          placeholder="All employees"
          data-testid="leave-admin-employee-filter"
          style={{ minWidth: 260 }}
        />
      </Group>

      <Alert
        color="blue"
        variant="light"
        data-testid="leave-admin-filter-note"
      >
        Filters below (branch, leave type, search) apply to loaded pages only.
        Click "Load more" to search further back.
      </Alert>

      <Group gap="sm" align="flex-end">
        <Select
          label="Branch"
          data={branchOptions}
          value={branchFilter}
          onChange={setBranchFilter}
          clearable
          placeholder="All branches"
          data-testid="leave-admin-branch-filter"
          style={{ minWidth: 200 }}
        />
        <Select
          label="Leave type"
          data={leaveTypeOptions}
          value={leaveTypeFilter}
          onChange={setLeaveTypeFilter}
          searchable
          clearable
          placeholder="All types"
          data-testid="leave-admin-leave-type-filter"
          style={{ minWidth: 200 }}
        />
        <TextInput
          label="Search"
          placeholder="Employee name or code"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.currentTarget.value)}
          data-testid="leave-admin-search"
          style={{ minWidth: 260 }}
        />
      </Group>

      {requests.isPending && (
        <Loader data-testid="leave-admin-requests-loading" />
      )}
      {requests.isError && (
        <Alert color="red" data-testid="leave-admin-requests-error">
          Could not load leave applications.
        </Alert>
      )}
      {requests.isSuccess && items.length === 0 && (
        <Text c="dimmed" data-testid="leave-admin-empty">
          No leave applications match the current filters.
        </Text>
      )}
      {requests.isSuccess && items.length > 0 && (
        <Table data-testid="leave-admin-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Employee</Table.Th>
              <Table.Th>Type</Table.Th>
              <Table.Th>From</Table.Th>
              <Table.Th>To</Table.Th>
              <Table.Th>Days</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Submitted</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((r) => {
              const emp = employeeMap.get(r.employee_id);
              const empLabel = emp
                ? `${emp.name} (${emp.code})`
                : r.employee_id.slice(0, 8);
              return (
                <Table.Tr
                  key={r.id}
                  data-testid={`leave-admin-row-${r.id}`}
                >
                  <Table.Td>{empLabel}</Table.Td>
                  <Table.Td>
                    {typeNameById.get(r.leave_type_id) ?? "—"}
                  </Table.Td>
                  <Table.Td>{r.from_date}</Table.Td>
                  <Table.Td>{r.to_date}</Table.Td>
                  <Table.Td>{fmt(r.days_requested)}</Table.Td>
                  <Table.Td>
                    <Badge color={statusColor(r.status)}>{r.status}</Badge>
                  </Table.Td>
                  <Table.Td>
                    {r.submitted_at
                      ? dayjs(r.submitted_at).format("YYYY-MM-DD")
                      : "—"}
                  </Table.Td>
                  <Table.Td>
                    <Button
                      size="xs"
                      variant="default"
                      data-testid={`leave-admin-open-${r.id}`}
                      onClick={() =>
                        navigate(`/leave/requests/${r.id}`, {
                          state: { returnTo: "/leave/admin" },
                        })}
                    >
                      Open
                    </Button>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      )}

      {requests.hasNextPage && (
        <Group justify="center">
          <Button
            variant="default"
            data-testid="leave-admin-load-more"
            loading={requests.isFetchingNextPage}
            onClick={() => requests.fetchNextPage()}
          >
            Load more
          </Button>
        </Group>
      )}
    </Stack>
  );
}