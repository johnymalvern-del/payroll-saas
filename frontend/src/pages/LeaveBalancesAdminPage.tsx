import { useMemo, useState } from "react";
import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Badge, Button, Card, Group, Loader, Select, Stack, Table,
  Text, TextInput, Title,
} from "@mantine/core";
import dayjs from "dayjs";
import { useMe } from "../auth/useMe";
import { fetchEmployeesPage } from "../api/employees";
import { fetchLeaveTypes } from "../api/leaveTypes";
import {
  fetchLeaveBalances,
  runAccruals,
  type LeaveBalanceOut,
} from "../api/leaveBalances";
import { AdjustBalanceModal } from "../components/Leave/AdjustBalanceModal";

function fmt(s: string): string {
  const n = Number(s);
  return Number.isFinite(n) ? n.toFixed(2) : s;
}

export function LeaveBalancesAdminPage() {
  const me = useMe();
  const qc = useQueryClient();
  const permissions = me.data?.permissions ?? [];
  const canView = permissions.includes("leave_approve");
  const canRunAccruals = permissions.includes("user_manage");

  const [employeeFilter, setEmployeeFilter] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [fromCycle, setFromCycle] = useState("");
  const [toCycle, setToCycle] = useState("");
  const [adjustTarget, setAdjustTarget] = useState<LeaveBalanceOut | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const employees = useQuery({
    queryKey: ["employees", "for-balances"],
    queryFn: () => fetchEmployeesPage({ limit: 500, include_terminated: true }),
    staleTime: 5 * 60 * 1000,
    enabled: canView,
  });

  const types = useQuery({
    queryKey: ["leave_types"],
    queryFn: fetchLeaveTypes,
    staleTime: 5 * 60 * 1000,
    enabled: canView,
  });

  const q = useInfiniteQuery({
    queryKey: [
      "leave_balances",
      "admin",
      employeeFilter,
      typeFilter,
      fromCycle,
      toCycle,
    ],
    queryFn: ({ pageParam }) =>
      fetchLeaveBalances({
        employee_id: employeeFilter ?? undefined,
        leave_type_id: typeFilter ?? undefined,
        cycle_start_gte: fromCycle || undefined,
        cycle_start_lte: toCycle || undefined,
        limit: 100,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: canView,
  });

  const employeeById = useMemo(() => {
    const m = new Map<string, { label: string; code: string }>();
    for (const e of employees.data?.items ?? []) {
      m.set(e.id, {
        label: `${e.first_name} ${e.last_name}`,
        code: e.employee_code,
      });
    }
    return m;
  }, [employees.data]);

  const typeNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const t of types.data?.items ?? []) m.set(t.id, t.name);
    return m;
  }, [types.data]);

  const accrMut = useMutation({
    mutationFn: () => runAccruals(),
    onSuccess: (out) => {
      setActionMsg(
        `Accruals run: ${out.rows_written} row(s) written across ${out.employees_touched} employee(s).`,
      );
      qc.invalidateQueries({ queryKey: ["leave_balances"] });
    },
    onError: () => setActionMsg("Could not run accruals. Please try again."),
  });

  if (me.isLoading) {
    return <Loader data-testid="balances-admin-loading" />;
  }
  if (!canView) {
    return (
      <Alert color="yellow" data-testid="balances-admin-no-permission">
        You do not have permission to view leave balances.
      </Alert>
    );
  }

  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  const accrStale = q.data?.pages[0]?.accrual_stale ?? false;
  const accrAsOf = q.data?.pages[0]?.accrued_as_of ?? null;

  const employeeOptions = (employees.data?.items ?? []).map((e) => ({
    value: e.id,
    label: `${e.first_name} ${e.last_name} (${e.employee_code})`,
  }));
  const typeOptions = (types.data?.items ?? []).map((t) => ({
    value: t.id,
    label: t.name,
  }));

  const employeeLabelFor = (b: LeaveBalanceOut) => {
    const e = employeeById.get(b.employee_id);
    return e ? `${e.label} (${e.code})` : b.employee_id;
  };

  return (
    <Stack gap="md" data-testid="leave-balances-admin-page">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Leave Balances</Title>
          <Text size="sm" c="dimmed">
            Adjust balances and run accruals across your scope.
          </Text>
        </div>
        {canRunAccruals && (
          <Button
            data-testid="balances-run-accruals"
            loading={accrMut.isPending}
            onClick={() => accrMut.mutate()}
          >
            Run accruals
          </Button>
        )}
      </Group>

      {actionMsg && (
        <Alert
          color={accrMut.isError ? "red" : "green"}
          data-testid="balances-action-msg"
          withCloseButton
          onClose={() => setActionMsg(null)}
        >
          {actionMsg}
        </Alert>
      )}

      {accrStale && (
        <Alert color="yellow" data-testid="balances-accrual-stale">
          Accruals have not been run recently.
          {accrAsOf
            ? ` Last run: ${dayjs(accrAsOf).format("YYYY-MM-DD HH:mm")}`
            : " No run recorded."}
        </Alert>
      )}

      <Card withBorder padding="md">
        <Group align="flex-end" gap="sm">
          <Select
            label="Employee"
            placeholder="All"
            data={employeeOptions}
            value={employeeFilter}
            onChange={setEmployeeFilter}
            searchable
            clearable
            style={{ minWidth: 220 }}
            data-testid="balances-filter-employee"
          />
          <Select
            label="Leave type"
            placeholder="All"
            data={typeOptions}
            value={typeFilter}
            onChange={setTypeFilter}
            clearable
            style={{ minWidth: 180 }}
            data-testid="balances-filter-type"
          />
          <TextInput
            label="Cycle from"
            type="date"
            value={fromCycle}
            onChange={(e) => setFromCycle(e.currentTarget.value)}
            data-testid="balances-filter-from"
          />
          <TextInput
            label="Cycle to"
            type="date"
            value={toCycle}
            onChange={(e) => setToCycle(e.currentTarget.value)}
            data-testid="balances-filter-to"
          />
        </Group>
      </Card>

      {q.isLoading && <Loader data-testid="balances-admin-table-loading" />}

      {q.isError && (
        <Alert color="red" data-testid="balances-admin-error">
          Could not load leave balances.
        </Alert>
      )}

      {!q.isLoading && !q.isError && items.length === 0 && (
        <Alert color="blue" data-testid="balances-admin-empty">
          No leave balances match these filters.
        </Alert>
      )}

      {items.length > 0 && (
        <Card withBorder padding="md">
          <Table data-testid="balances-admin-table">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Employee</Table.Th>
                <Table.Th>Type</Table.Th>
                <Table.Th>Cycle</Table.Th>
                <Table.Th>Entitled</Table.Th>
                <Table.Th>Accrued</Table.Th>
                <Table.Th>Pending</Table.Th>
                <Table.Th>Taken</Table.Th>
                <Table.Th>Adjusted</Table.Th>
                <Table.Th>Available</Table.Th>
                <Table.Th></Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((b) => {
                const emp = employeeById.get(b.employee_id);
                const typeName = typeNameById.get(b.leave_type_id) ?? "—";
                return (
                  <Table.Tr key={b.id} data-testid={`balances-row-${b.id}`}>
                    <Table.Td>
                      {emp ? `${emp.label} (${emp.code})` : b.employee_id}
                    </Table.Td>
                    <Table.Td>{typeName}</Table.Td>
                    <Table.Td>
                      <Badge variant="light" size="sm">
                        {dayjs(b.cycle_start).format("MMM YYYY")}
                      </Badge>
                    </Table.Td>
                    <Table.Td>{fmt(b.entitled)}</Table.Td>
                    <Table.Td>{fmt(b.accrued)}</Table.Td>
                    <Table.Td>{fmt(b.pending)}</Table.Td>
                    <Table.Td>{fmt(b.taken)}</Table.Td>
                    <Table.Td>{fmt(b.adjusted)}</Table.Td>
                    <Table.Td>
                      <Text fw={600}>{fmt(b.available)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Button
                        size="xs"
                        variant="light"
                        data-testid={`balances-adjust-${b.id}`}
                        onClick={() => setAdjustTarget(b)}
                      >
                        Adjust
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
          {q.hasNextPage && (
            <Group justify="center" mt="md">
              <Button
                variant="default"
                data-testid="balances-load-more"
                loading={q.isFetchingNextPage}
                onClick={() => q.fetchNextPage()}
              >
                Load more
              </Button>
            </Group>
          )}
        </Card>
      )}

      {adjustTarget && (
        <AdjustBalanceModal
          opened
          onClose={() => setAdjustTarget(null)}
          balance={adjustTarget}
          employeeLabel={employeeLabelFor(adjustTarget)}
          leaveTypeLabel={typeNameById.get(adjustTarget.leave_type_id) ?? "—"}
          onSuccess={() => setAdjustTarget(null)}
        />
      )}
    </Stack>
  );
}