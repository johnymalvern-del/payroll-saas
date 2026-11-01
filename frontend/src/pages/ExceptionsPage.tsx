import { useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  MultiSelect,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { fetchEmployees } from "../api/employees";
import {
  BulkApiError,
  bulkResolveExceptions,
  fetchExceptions,
  resolveException,
  type BulkResolveIn,
  type BulkResolveItemIn,
  type BulkResolveOut,
  type ExceptionList,
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

const PAGE_SIZE = 100;

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

type BulkAction = "apply_suggestion" | "dismiss";

function mapBulkError(code: string): string {
  switch (code) {
    case "bulk_validation_failed":
      return strings.exceptions.bulk.errValidationFailed;
    case "token_mismatch":
      return strings.exceptions.bulk.errTokenMismatch;
    case "batch_failed":
      return strings.exceptions.bulk.errBatchFailed;
    default:
      return mapErrorCode(code);
  }
}

export function ExceptionsPage() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("open");
  const [typeFilter, setTypeFilter] = useState<string[]>([]);
  const [modal, setModal] = useState<ModalState>(null);
  const [serverError, setServerError] = useState<string | null>(null);

  // Bulk-resolve state
  const [bulkMode, setBulkMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkAction, setBulkAction] = useState<BulkAction>("apply_suggestion");
  const [bulkNote, setBulkNote] = useState("");
  const [bulkDryRun, setBulkDryRun] = useState<BulkResolveOut | null>(null);
  const [bulkResult, setBulkResult] = useState<BulkResolveOut | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkConfirmOpen, setBulkConfirmOpen] = useState(false);

  const employees = useQuery({
    queryKey: ["refs", "employees"],
    queryFn: () => fetchEmployees(),
    staleTime: 5 * 60 * 1000,
  });

  const exceptions = useInfiniteQuery({
    queryKey: ["exceptions", statusFilter],
    queryFn: ({ pageParam }) =>
      fetchExceptions({
        status: statusFilter,
        cursor: pageParam,
        limit: PAGE_SIZE,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const resolve = useMutation({
    mutationFn: (vars: { id: string; body: ResolveRequest }) =>
      resolveException(vars.id, vars.body),
    onSuccess: () => {
      setModal(null);
      setServerError(null);
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      qc.invalidateQueries({ queryKey: ["attendance"] });
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

  const openModal = (next: NonNullable<ModalState>) => {
    setServerError(null);
    setModal(next);
  };

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

  const rawItems: ExceptionRow[] =
    exceptions.data?.pages.flatMap((p: ExceptionList) => p.items) ?? [];
  const items =
    typeFilter.length === 0
      ? rawItems
      : rawItems.filter((r) => typeFilter.includes(r.type));

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    setSelectedIds(new Set(items.map((r) => r.id)));
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
  };

  const enterBulk = () => {
    setBulkMode(true);
    setBulkDryRun(null);
    setBulkResult(null);
    setBulkError(null);
  };

  const exitBulk = () => {
    setBulkMode(false);
    setSelectedIds(new Set());
    setBulkDryRun(null);
    setBulkResult(null);
    setBulkError(null);
    setBulkNote("");
    setBulkAction("apply_suggestion");
  };

  const bulkItems: BulkResolveItemIn[] = Array.from(selectedIds).map((id) => ({
    exception_id: id,
    action: bulkAction,
    custom_adjustment: null,
    note: bulkAction === "dismiss" ? bulkNote : null,
  }));

  const allOk =
    bulkDryRun !== null &&
    bulkDryRun.results.length === bulkItems.length &&
    bulkDryRun.results.every((r) => r.ok);

  const canDryRun =
    !bulkBusy &&
    selectedIds.size > 0 &&
    (bulkAction !== "dismiss" || bulkNote.trim().length >= 3);

  const runBulkDryRun = async () => {
    setBulkBusy(true);
    setBulkError(null);
    setBulkDryRun(null);
    setBulkResult(null);
    try {
      const data = await bulkResolveExceptions({ items: bulkItems });
      setBulkDryRun(data);
    } catch (err) {
      setBulkError(
        err instanceof BulkApiError
          ? mapBulkError(err.code)
          : strings.genericError,
      );
    } finally {
      setBulkBusy(false);
    }
  };

  const runBulkConfirm = async () => {
    if (!bulkDryRun) return;
    setBulkBusy(true);
    setBulkError(null);
    const token = bulkDryRun.token;
    const body: BulkResolveIn = { items: bulkItems, token };
    try {
      const data = await bulkResolveExceptions(body);
      setBulkResult(data);
      setBulkDryRun(null);
      setBulkConfirmOpen(false);
      setSelectedIds(new Set());
      await qc.invalidateQueries({ queryKey: ["exceptions"] });
      await qc.invalidateQueries({ queryKey: ["attendance"] });
    } catch (err) {
      setBulkConfirmOpen(false);
      if (err instanceof BulkApiError) {
        setBulkError(mapBulkError(err.code));
        if (err.code === "bulk_validation_failed" && err.details?.results) {
          setBulkDryRun({
            results: err.details.results,
            applied: 0,
            dry_run: true,
            token,
          });
        }
      } else {
        setBulkError(strings.genericError);
      }
    } finally {
      setBulkBusy(false);
    }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>{strings.exceptions.title}</Title>
        <Button
          variant={bulkMode ? "filled" : "default"}
          onClick={bulkMode ? exitBulk : enterBulk}
          data-testid="exceptions-bulk-toggle"
        >
          {bulkMode ? strings.exceptions.bulk.exit : strings.exceptions.bulk.enter}
        </Button>
      </Group>
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
      {serverError ? (
        <Alert
          color="red"
          withCloseButton
          onClose={() => setServerError(null)}
          data-testid="direct-error"
        >
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
      {bulkMode ? (
        <Paper withBorder p="md" data-testid="exceptions-bulk-bar">
          <Stack gap="sm">
            <Group gap="sm" wrap="wrap" align="end">
              <Select
                label={strings.exceptions.bulk.actionLabel}
                data={[
                  {
                    value: "apply_suggestion",
                    label: strings.exceptions.bulk.actionApplySuggestion,
                  },
                  {
                    value: "dismiss",
                    label: strings.exceptions.bulk.actionDismiss,
                  },
                ]}
                value={bulkAction}
                onChange={(v) => v && setBulkAction(v as BulkAction)}
                allowDeselect={false}
                data-testid="exceptions-bulk-action"
              />
              {bulkAction === "dismiss" ? (
                <TextInput
                  label={strings.exceptions.bulk.noteLabel}
                  value={bulkNote}
                  onChange={(e) => setBulkNote(e.currentTarget.value)}
                  data-testid="exceptions-bulk-note"
                />
              ) : null}
              <Button
                variant="default"
                onClick={selectAll}
                data-testid="exceptions-bulk-select-all"
              >
                {strings.exceptions.bulk.selectAll}
              </Button>
              <Button
                variant="default"
                onClick={clearSelection}
                data-testid="exceptions-bulk-clear"
              >
                {strings.exceptions.bulk.clear}
              </Button>
              <Text size="sm" c="dimmed">
                {strings.exceptions.bulk.selectedCount(selectedIds.size)}
              </Text>
            </Group>
            <Group gap="sm">
              <Button
                onClick={runBulkDryRun}
                disabled={!canDryRun}
                loading={bulkBusy}
                data-testid="exceptions-bulk-dry-run"
              >
                {strings.exceptions.bulk.dryRunButton}
              </Button>
              <Button
                onClick={() => setBulkConfirmOpen(true)}
                disabled={!allOk || bulkBusy}
                data-testid="exceptions-bulk-confirm"
              >
                {strings.exceptions.bulk.confirmButton}
              </Button>
            </Group>
            {bulkError ? (
              <Alert color="red" data-testid="exceptions-bulk-error">
                {bulkError}
              </Alert>
            ) : null}
            {bulkDryRun || bulkResult ? (
              <Stack gap={4} data-testid="exceptions-bulk-results">
                <Text size="sm" fw={500}>
                  {bulkResult
                    ? strings.exceptions.bulk.appliedTitle
                    : strings.exceptions.bulk.resultsTitle}
                </Text>
                {(bulkResult ?? bulkDryRun)!.results.map((r) => (
                  <Text
                    key={r.index}
                    size="xs"
                    data-testid={`exceptions-bulk-row-${r.index}`}
                  >
                    #{r.index} ·{" "}
                    {r.ok
                      ? strings.exceptions.bulk.resultsOkLabel
                      : `${strings.exceptions.bulk.resultsFailLabel}: ${mapBulkError(
                          r.error_code ?? "unknown_error",
                        )}`}
                  </Text>
                ))}
                {bulkResult ? (
                  <Text size="xs" c="dimmed">
                    {strings.exceptions.bulk.appliedCount(bulkResult.applied)}
                  </Text>
                ) : null}
              </Stack>
            ) : null}
          </Stack>
        </Paper>
      ) : null}
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
                  onCustom={() =>
                    openModal({ exception: row, action: "custom" })
                  }
                  onDismiss={() =>
                    openModal({ exception: row, action: "dismiss" })
                  }
                  busy={resolve.isPending && resolve.variables?.id === row.id}
                  selectable={bulkMode}
                  selected={selectedIds.has(row.id)}
                  onToggle={() => toggleSelect(row.id)}
                />
              );
            })}
          </Stack>
        )}
      </Paper>
      {exceptions.hasNextPage ? (
        <Group justify="center">
          <Button
            variant="default"
            onClick={() => exceptions.fetchNextPage()}
            loading={exceptions.isFetchingNextPage}
            data-testid="exceptions-load-more"
          >
            {strings.exceptions.loadMore}
          </Button>
        </Group>
      ) : null}
      <ResolveModal
        opened={modal !== null}
        exception={modal?.exception ?? null}
        initialAction={modal?.action ?? "custom"}
        onClose={() => {
          setModal(null);
        }}
        onResolve={(req) => {
          if (!modal) return;
          resolve.mutate({ id: modal.exception.id, body: req });
        }}
        busy={resolve.isPending}
        serverError={serverError}
      />
      <Modal
        opened={bulkConfirmOpen}
        onClose={() => {
          if (bulkBusy) return;
          setBulkConfirmOpen(false);
        }}
        title={strings.exceptions.bulk.confirmTitle}
        data-testid="exceptions-bulk-confirm-modal"
      >
        <Stack gap="sm">
          <Text size="sm">{strings.exceptions.bulk.confirmBody}</Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => setBulkConfirmOpen(false)}
              disabled={bulkBusy}
              data-testid="exceptions-bulk-confirm-cancel"
            >
              {strings.exceptions.bulk.cancel}
            </Button>
            <Button
              onClick={runBulkConfirm}
              loading={bulkBusy}
              data-testid="exceptions-bulk-confirm-apply"
            >
              {strings.exceptions.bulk.confirmApply}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}