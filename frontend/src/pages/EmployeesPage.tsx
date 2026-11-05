import { useMemo, useState } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import {
  EmployeesApiError,
  fetchEmployeesPage,
  patchEmployee,
  type EmployeeOut,
} from "../api/employees";
import { EmployeeForm } from "../components/Employees/EmployeeForm";
import { mapErrorCode } from "../api/errors";
import { strings } from "../lib/strings";
import { colors } from "../theme/colors";

const PAGE_SIZE = 100;

const STATUS_OPTIONS = [
  { value: "active", label: strings.employees.statusActive },
  { value: "on_leave", label: strings.employees.statusOnLeave },
  { value: "suspended", label: strings.employees.statusSuspended },
  { value: "terminated", label: strings.employees.statusTerminated },
];

function statusColor(status: string): string {
  switch (status) {
    case "active":
      return "green";
    case "on_leave":
      return "blue";
    case "suspended":
      return "orange";
    case "terminated":
      return "gray";
    default:
      return "gray";
  }
}

export function EmployeesPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [debouncedSearch] = useDebouncedValue(search, 300);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [includeTerminated, setIncludeTerminated] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EmployeeOut | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  const employees = useInfiniteQuery({
    queryKey: [
      "employees",
      "list",
      debouncedSearch,
      statusFilter,
      includeTerminated,
    ],
    queryFn: ({ pageParam }) =>
      fetchEmployeesPage({
        cursor: pageParam,
        limit: PAGE_SIZE,
        last_name: debouncedSearch || undefined,
        status: statusFilter ?? undefined,
        include_terminated: includeTerminated,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const items = useMemo(
    () => (employees.data?.pages ?? []).flatMap((p) => p.items),
    [employees.data],
  );

  const terminate = useMutation({
    mutationFn: (emp: EmployeeOut) =>
      patchEmployee(emp.id, {
        row_version: emp.row_version,
        status: "terminated",
      }),
    onSuccess: () => {
      setPageError(null);
      qc.invalidateQueries({ queryKey: ["employees"] });
    },
    onError: (err) => {
      const code =
        err instanceof EmployeesApiError
          ? err.code
          : err instanceof Error
            ? err.message
            : undefined;
      if (code === "record_changed")
        setPageError(strings.employees.errRecordChanged);
      else if (code === "duplicate_code")
        setPageError(strings.employees.errDupCode);
      else setPageError(code ? mapErrorCode(code) : strings.genericError);
    },
  });

  const confirmTerminate = (emp: EmployeeOut) => {
    const name = `${emp.first_name} ${emp.last_name}`;
    if (!window.confirm(strings.employees.terminateConfirm(name))) return;
    terminate.mutate(emp);
  };

  const openCreate = () => {
    setEditTarget(null);
    setFormOpen(true);
  };

  const openEdit = (emp: EmployeeOut) => {
    setEditTarget(emp);
    setFormOpen(true);
  };

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>{strings.employees.title}</Title>
        <Button onClick={openCreate} data-testid="employees-new">
          {strings.employees.newButton}
        </Button>
      </Group>

      {pageError ? (
        <Paper withBorder p="sm">
          <Group justify="space-between" align="center">
            <Text c="red" size="sm" data-testid="employees-page-error">
              {pageError}
            </Text>
            <Button
              size="xs"
              variant="default"
              onClick={() => setPageError(null)}
            >
              {strings.common.dismiss}
            </Button>
          </Group>
        </Paper>
      ) : null}

      <Paper withBorder p="md">
        <Group gap="sm" wrap="wrap" align="end">
          <TextInput
            label={strings.employees.searchPlaceholder}
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            data-testid="employees-search"
          />
          <Select
            label={strings.employees.allStatuses}
            data={STATUS_OPTIONS}
            value={statusFilter}
            onChange={setStatusFilter}
            clearable
            data-testid="employees-status-filter"
          />
          <Checkbox
            label={strings.employees.includeTerminated}
            checked={includeTerminated}
            onChange={(e) => setIncludeTerminated(e.currentTarget.checked)}
            data-testid="employees-include-terminated"
          />
        </Group>
      </Paper>

      <Paper withBorder p="md">
        {employees.isPending ? (
          <Group justify="center" p="xl">
            <Loader />
          </Group>
        ) : employees.isError ? (
          <Group justify="space-between" align="center">
            <Text c="red" size="sm" data-testid="employees-error">
              {strings.employees.error}
            </Text>
            <Button
              size="xs"
              variant="default"
              onClick={() => employees.refetch()}
              data-testid="employees-retry"
            >
              {strings.employees.retry}
            </Button>
          </Group>
        ) : items.length === 0 ? (
          <Text c="dimmed">{strings.employees.empty}</Text>
        ) : (
          <Stack gap="sm" data-testid="employees-list">
            {items.map((emp) => {
              const name = `${emp.first_name} ${emp.last_name}`.trim();
              const terminating =
                terminate.isPending &&
                terminate.variables?.id === emp.id;
              return (
                <Paper
                  key={emp.id}
                  withBorder
                  p="sm"
                  data-testid={`employee-${emp.id}`}
                >
                  <Group justify="space-between" align="center" wrap="nowrap">
                    <Stack gap={2}>
                      <Group gap="sm">
                        <Text fw={600}>{name || emp.employee_code}</Text>
                        <Badge color={statusColor(emp.status)} variant="light">
                          {emp.status.replace(/_/g, " ")}
                        </Badge>
                      </Group>
                      <Text size="xs" c="dimmed">
                        {emp.employee_code}
                        {emp.job_title ? ` · ${emp.job_title}` : ""}
                      </Text>
                    </Stack>
                    <Group gap="xs">
                      <Button
                        size="xs"
                        variant="default"
                        onClick={() => openEdit(emp)}
                        data-testid={`employee-edit-${emp.id}`}
                      >
                        {strings.employees.editButton}
                      </Button>
                      <Button
                        size="xs"
                        variant="default"
                        color={colors.problem}
                        onClick={() => confirmTerminate(emp)}
                        loading={terminating}
                        disabled={emp.status === "terminated"}
                        data-testid={`employee-terminate-${emp.id}`}
                      >
                        {strings.employees.terminateButton}
                      </Button>
                    </Group>
                  </Group>
                </Paper>
              );
            })}
          </Stack>
        )}
      </Paper>

      {employees.hasNextPage ? (
        <Group justify="center">
          <Button
            variant="default"
            onClick={() => employees.fetchNextPage()}
            loading={employees.isFetchingNextPage}
            data-testid="employees-load-more"
          >
            {strings.employees.loadMore}
          </Button>
        </Group>
      ) : null}

      <EmployeeForm
        opened={formOpen}
        initial={editTarget}
        onClose={() => {
          setFormOpen(false);
          setEditTarget(null);
        }}
        onSuccess={() => {
          qc.invalidateQueries({ queryKey: ["employees"] });
        }}
      />
    </Stack>
  );
}