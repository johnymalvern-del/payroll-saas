import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Group,
  Loader,
  MultiSelect,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { fetchEmployees } from "../api/employees";
import {
  fetchExceptions,
  resolveException,
  type ExceptionRow,
  type ResolveRequest,
} from "../api/exceptions";
import { mapErrorCode } from "../api/errors";
import { ExceptionCard } from "../components/Exceptions/ExceptionCard";
import { ResolveModal } from "../components/Exceptions/ResolveModal";
import { suggestionSummary } from "../lib/exceptionSummary";
import {
  EXCEPTION_TYPE_ORDER,
  exceptionTypeLabel,
  strings,
} from "../lib/strings";

const STATUS_OPTIONS = [
  { label: strings.exceptions.statusOpen, value: "open" },
  { label: strings.exceptions.statusResolved, value: "resolved" },
  { label: strings.exceptions.statusDismissed, value: "dismissed" },
];

const TYPE_OPTIONS = EXCEPTION_TYPE_ORDER.map((code) => ({
  value: code,
  label: exceptionTypeLabel(code),
}));

type ModalState = {
  exception: ExceptionRow;
  action: "custom" | "dismiss";
} | null;

export function ExceptionsPage() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("open");
  const [typeFilter, setTypeFilter] = useState<string[]>([]);
  const [modal, setModal] = useState<ModalState>(null);
  const [serverError, setServerError] = useState<string | null>(null);

  const employees = useQuery({
    queryKey: ["refs", "employees"],
    queryFn: () => fetchEmployees(),
    staleTime: 5 * 60 * 1000,
  });

  const exceptions = useQuery({
    queryKey: ["exceptions", statusFilter],
    queryFn: () => fetchExceptions({ status: statusFilter }),
  });

  const resolve = useMutation({
    mutationFn: (vars: { id: string; body: ResolveRequest }) =>
      resolveException(vars.id, vars.body),
    onSuccess: () => {
      setModal(null);
      setServerError(null);
      qc.invalidateQueries({ queryKey: ["exceptions"] });
    },
    onError: (err) => {
      const code = err instanceof Error ? err.message : "unknown_error";
      setServerError(mapErrorCode(code));
    },
  });

  const empMap = new Map<string, { name: string; code: string }>();
  for (const e of employees.data ?? []) {
    empMap.set(e.id, {
      name: `${e.first_name} ${e.last_name}`.trim(),
      code: e.employee_code,
    });
  }

  const applySuggestion = (row: ExceptionRow) => {
    setServerError(null);
    const summary =
      suggestionSummary(row.suggested_fix) ?? exceptionTypeLabel(row.type);
    if (!window.confirm(strings.exceptions.applyConfirm(summary))) return;
    resolve.mutate({
      id: row.id,
      body: { action: "apply_suggestion", custom_adjustment: null, note: null },
    });
  };

  const rawItems = exceptions.data?.items ?? [];
  const items =
    typeFilter.length === 0
      ? rawItems
      : rawItems.filter((r) => typeFilter.includes(r.type));

  return (
    <Stack gap="md">
      <Title order={2}>{strings.exceptions.title}</Title>
      {employees.isError ? (
        <Alert color="red" data-testid="employees-error">
          <Group justify="space-between" align="center">
            <Text size="sm">{strings.exceptions.employeesError}</Text>
            <Button
              size="xs"
              variant="default"
              onClick={() => employees.refetch()}
              data-testid="employees-retry"
            >
              {strings.exceptions.employeesRetry}
            </Button>
          </Group>
        </Alert>
      ) : null}
      {serverError && modal === null ? (
        <Alert color="red" data-testid="direct-error">
          {serverError}
        </Alert>
      ) : null}
      <Paper withBorder p="md">
        <Group gap="sm" wrap="wrap" align="end">
          <SegmentedControl
            value={statusFilter}
            onChange={(v) => setStatusFilter(v)}
            data={STATUS_OPTIONS}
          />
          <MultiSelect
            label={strings.exceptions.typeFilter}
            data={TYPE_OPTIONS}
            value={typeFilter}
            onChange={setTypeFilter}
            placeholder={strings.exceptions.allTypes}
            description={strings.exceptions.multiTypeNote}
            clearable
          />
        </Group>
      </Paper>
      <Paper withBorder p="md">
        {exceptions.isPending ? (
          <Group justify="center" p="xl">
            <Loader />
          </Group>
        ) : exceptions.isError ? (
          <Text c="red">{strings.exceptions.error}</Text>
        ) : items.length === 0 ? (
          <Text c="dimmed">{strings.exceptions.empty}</Text>
        ) : (
          <Stack gap="sm">
            {items.map((row) => {
              const info = empMap.get(row.employee_id);
              return (
                <ExceptionCard
                  key={row.id}
                  exception={row}
                  employeeName={info?.name ?? row.employee_id.slice(0, 8)}
                  employeeCode={info?.code ?? ""}
                  onApplySuggestion={() => applySuggestion(row)}
                  onCustom={() => setModal({ exception: row, action: "custom" })}
                  onDismiss={() =>
                    setModal({ exception: row, action: "dismiss" })
                  }
                  busy={resolve.isPending}
                />
              );
            })}
          </Stack>
        )}
      </Paper>
      <ResolveModal
        opened={modal !== null}
        exception={modal?.exception ?? null}
        initialAction={modal?.action ?? "custom"}
        onClose={() => {
          setModal(null);
          setServerError(null);
        }}
        onResolve={(req) => {
          if (!modal) return;
          resolve.mutate({ id: modal.exception.id, body: req });
        }}
        busy={resolve.isPending}
        serverError={serverError}
      />
    </Stack>
  );
}
