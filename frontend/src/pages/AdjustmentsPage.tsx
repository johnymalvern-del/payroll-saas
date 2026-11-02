import { useMemo, useState } from "react";
import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  MultiSelect,
  Paper,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchEmployees } from "../api/employees";
import {
  ADJUSTMENT_OUTCOMES,
  AdjustBulkError,
  bulkAdjust,
  type AdjustmentOutcome,
  type BulkAdjustIn,
  type BulkAdjustItemIn,
  type BulkAdjustOut,
} from "../api/adjustments";
import { fetchReasonCodes } from "../api/reasonCodes";
import { mapErrorCode } from "../api/errors";
import { DEFAULT_SITE_TZ } from "../lib/config";
import { strings } from "../lib/strings";

dayjs.extend(utc);
dayjs.extend(timezone);

const BULK_CAP = 200;

function mapBulkAdjustError(code: string): string {
  switch (code) {
    case "bulk_validation_failed":
      return strings.adjustments.bulk.errValidationFailed;
    case "token_mismatch":
      return strings.adjustments.bulk.errTokenMismatch;
    case "batch_failed":
      return strings.adjustments.bulk.errBatchFailed;
    default:
      return mapErrorCode(code);
  }
}

function enumerateDates(from: string, to: string): string[] {
  if (!from || !to) return [];
  const start = dayjs(from);
  const end = dayjs(to);
  if (!start.isValid() || !end.isValid() || end.isBefore(start, "day")) {
    return [];
  }
  const out: string[] = [];
  let cur = start;
  while (!cur.isAfter(end, "day") && out.length < BULK_CAP + 1) {
    out.push(cur.format("YYYY-MM-DD"));
    cur = cur.add(1, "day");
  }
  return out;
}

function buildItem(
  employeeId: string,
  dateStr: string,
  outcome: AdjustmentOutcome,
  timeIn: string,
  timeOut: string,
  reasonCode: string,
  note: string,
): BulkAdjustItemIn {
  if (outcome === "worked" && timeIn && timeOut) {
    const tin = dayjs.tz(`${dateStr}T${timeIn}:00`, DEFAULT_SITE_TZ);
    let tout = dayjs.tz(`${dateStr}T${timeOut}:00`, DEFAULT_SITE_TZ);
    if (!tout.isAfter(tin)) tout = tout.add(1, "day");
    return {
      employee_id: employeeId,
      work_date: dateStr,
      outcome,
      time_in: tin.toISOString(),
      time_out: tout.toISOString(),
      reason_code: reasonCode,
      note: note ? note : null,
    };
  }
  return {
    employee_id: employeeId,
    work_date: dateStr,
    outcome,
    time_in: null,
    time_out: null,
    reason_code: reasonCode,
    note: note ? note : null,
  };
}

export function AdjustmentsPage() {
  const qc = useQueryClient();
  const [outcome, setOutcome] = useState<AdjustmentOutcome>("worked");
  const [timeIn, setTimeIn] = useState("08:00");
  const [timeOut, setTimeOut] = useState("16:30");
  const [fromDate, setFromDate] = useState(dayjs().format("YYYY-MM-DD"));
  const [toDate, setToDate] = useState(dayjs().format("YYYY-MM-DD"));
  const [employeeIds, setEmployeeIds] = useState<string[]>([]);
  const [reasonCode, setReasonCode] = useState("");
  const [note, setNote] = useState("");
  const [dryRun, setDryRun] = useState<BulkAdjustOut | null>(null);
  const [result, setResult] = useState<BulkAdjustOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const employees = useQuery({
    queryKey: ["refs", "employees"],
    queryFn: () => fetchEmployees(),
    staleTime: 5 * 60 * 1000,
  });

  const codesQuery = useQuery({
    queryKey: ["refs", "reason_codes"],
    queryFn: fetchReasonCodes,
    staleTime: 5 * 60 * 1000,
  });
  const codes = codesQuery.data ?? [];
  const selected = codes.find((c) => c.code === reasonCode) ?? null;
  const requiresNote =
    selected?.requires_note ?? (reasonCode === "other");

  const empOptions = useMemo(
    () =>
      (employees.data ?? []).map((e) => ({
        value: e.id,
        label: `${e.first_name} ${e.last_name} (${e.employee_code})`,
      })),
    [employees.data],
  );

  const requiresTimes = outcome === "worked";
  const rangeOk =
    !!fromDate && !!toDate && !dayjs(toDate).isBefore(dayjs(fromDate), "day");
  const dates = useMemo(
    () => (rangeOk ? enumerateDates(fromDate, toDate) : []),
    [fromDate, toDate, rangeOk],
  );
  const totalRows = employeeIds.length * dates.length;
  const overCap = totalRows > BULK_CAP;
  const reasonCodeMissing = reasonCode.trim().length === 0;
  const noteOkForOther =
    !requiresNote || note.trim().length >= 10;

  const items: BulkAdjustItemIn[] = useMemo(() => {
    if (
      !rangeOk ||
      employeeIds.length === 0 ||
      dates.length === 0 ||
      reasonCodeMissing ||
      overCap
    ) {
      return [];
    }
    if (requiresTimes && (!timeIn || !timeOut)) return [];
    const out: BulkAdjustItemIn[] = [];
    for (const emp of employeeIds) {
      for (const d of dates) {
        out.push(
          buildItem(emp, d, outcome, timeIn, timeOut, reasonCode.trim(), note),
        );
      }
    }
    return out;
  }, [
    rangeOk,
    employeeIds,
    dates,
    reasonCodeMissing,
    overCap,
    requiresTimes,
    timeIn,
    timeOut,
    outcome,
    reasonCode,
    note,
  ]);

  const canDryRun =
    !busy &&
    items.length > 0 &&
    items.length <= BULK_CAP &&
    noteOkForOther;

  const allOk =
    dryRun !== null &&
    dryRun.results.length === items.length &&
    dryRun.results.every((r) => r.ok);

  const runDryRun = async () => {
    setBusy(true);
    setError(null);
    setDryRun(null);
    setResult(null);
    try {
      const body: BulkAdjustIn = { items };
      const data = await bulkAdjust(body);
      setDryRun(data);
    } catch (err) {
      setError(
        err instanceof AdjustBulkError
          ? mapBulkAdjustError(err.code)
          : strings.genericError,
      );
    } finally {
      setBusy(false);
    }
  };

  const runConfirm = async () => {
    if (!dryRun) return;
    setBusy(true);
    setError(null);
    const token = dryRun.token;
    try {
      const data = await bulkAdjust({ items, token });
      setResult(data);
      setDryRun(null);
      setConfirmOpen(false);
      await qc.invalidateQueries({ queryKey: ["attendance"] });
      await qc.invalidateQueries({ queryKey: ["exceptions"] });
    } catch (err) {
      setConfirmOpen(false);
      if (err instanceof AdjustBulkError) {
        setError(mapBulkAdjustError(err.code));
        if (err.code === "bulk_validation_failed" && err.results) {
          setDryRun({
            results: err.results,
            applied: 0,
            dry_run: true,
            token,
          });
        }
      } else {
        setError(strings.genericError);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack gap="md">
      <Title order={2}>{strings.adjustments.bulk.title}</Title>
      {error ? (
        <Alert
          color="red"
          withCloseButton
          onClose={() => setError(null)}
          data-testid="adjustments-bulk-error"
        >
          {error}
        </Alert>
      ) : null}
      {codesQuery.isError ? (
        <Alert color="red" data-testid="adjustments-reason-error">
          {strings.adjustments.reasonCodeError}
        </Alert>
      ) : null}
      <Paper withBorder p="md">
        <Stack gap="sm">
          <Select
            label={strings.adjustments.outcome}
            data={ADJUSTMENT_OUTCOMES.map((o) => ({
              value: o,
              label: o.replace(/_/g, " "),
            }))}
            value={outcome}
            onChange={(v) => v && setOutcome(v as AdjustmentOutcome)}
            allowDeselect={false}
            data-testid="adjustments-bulk-outcome"
          />
          {requiresTimes ? (
            <Group grow align="flex-end">
              <TextInput
                label={strings.adjustments.timeIn}
                type="time"
                value={timeIn}
                onChange={(e) => setTimeIn(e.currentTarget.value)}
                data-testid="adjustments-bulk-time-in"
              />
              <TextInput
                label={strings.adjustments.timeOut}
                type="time"
                value={timeOut}
                onChange={(e) => setTimeOut(e.currentTarget.value)}
                data-testid="adjustments-bulk-time-out"
              />
            </Group>
          ) : null}
          <Group grow align="flex-end">
            <TextInput
              label={strings.adjustments.bulk.fromDate}
              type="date"
              value={fromDate}
              onChange={(e) => setFromDate(e.currentTarget.value)}
              data-testid="adjustments-bulk-from"
            />
            <TextInput
              label={strings.adjustments.bulk.toDate}
              type="date"
              value={toDate}
              onChange={(e) => setToDate(e.currentTarget.value)}
              data-testid="adjustments-bulk-to"
            />
          </Group>
          {!rangeOk ? (
            <Text size="xs" c="red" data-testid="adjustments-bulk-range-err">
              {strings.adjustments.bulk.invalidRange}
            </Text>
          ) : null}
          <MultiSelect
            label={strings.adjustments.bulk.employees}
            data={empOptions}
            value={employeeIds}
            onChange={setEmployeeIds}
            searchable
            clearable
            data-testid="adjustments-bulk-employees"
          />
          <Select
            label={strings.adjustments.reasonCode}
            placeholder={strings.adjustments.selectReasonCode}
            data={codes.map((c) => ({ value: c.code, label: c.label }))}
            value={reasonCode || null}
            onChange={(v) => setReasonCode(v ?? "")}
            description={strings.adjustments.reasonCodeHint}
            required
            disabled={codesQuery.isLoading || codesQuery.isError}
            data-testid="adjustments-bulk-reason"
          />
          <Textarea
            label={strings.adjustments.note}
            value={note}
            onChange={(e) => setNote(e.currentTarget.value)}
            description={
              requiresNote ? strings.adjustments.noteOtherHint : undefined
            }
            error={
              requiresNote && note.trim().length > 0 && note.trim().length < 10
                ? strings.adjustments.noteRequiredForOther
                : undefined
            }
            minRows={2}
            data-testid="adjustments-bulk-note"
          />
          <Group justify="space-between" align="center">
            <Text size="sm" c="dimmed" data-testid="adjustments-bulk-count">
              {strings.adjustments.bulk.itemCountLabel(items.length)}
            </Text>
            <Group gap="sm">
              <Button
                onClick={runDryRun}
                disabled={!canDryRun}
                loading={busy}
                data-testid="adjustments-bulk-dry-run"
              >
                {strings.adjustments.bulk.dryRunButton}
              </Button>
              <Button
                onClick={() => setConfirmOpen(true)}
                disabled={!allOk || busy}
                data-testid="adjustments-bulk-confirm"
              >
                {strings.adjustments.bulk.confirmButton}
              </Button>
            </Group>
          </Group>
          {overCap ? (
            <Alert color="yellow" data-testid="adjustments-bulk-over-cap">
              {strings.adjustments.bulk.overCapWarning}
            </Alert>
          ) : null}
          {dryRun || result ? (
            <Stack gap={4} data-testid="adjustments-bulk-results">
              <Text size="sm" fw={500}>
                {result
                  ? strings.adjustments.bulk.appliedTitle
                  : strings.adjustments.bulk.resultsTitle}
              </Text>
              {(result ?? dryRun)!.results.map((r) => (
                <Text
                  key={r.index}
                  size="xs"
                  data-testid={`adjustments-bulk-row-${r.index}`}
                >
                  #{r.index} · {r.work_date} ·{" "}
                  {r.ok
                    ? strings.adjustments.bulk.resultsOkLabel
                    : `${strings.adjustments.bulk.resultsFailLabel}: ${mapBulkAdjustError(
                        r.error_code ?? "unknown_error",
                      )}`}
                </Text>
              ))}
              {result ? (
                <Text size="xs" c="dimmed">
                  {strings.adjustments.bulk.appliedCount(result.applied)}
                </Text>
              ) : null}
            </Stack>
          ) : null}
        </Stack>
      </Paper>
      <Modal
        opened={confirmOpen}
        onClose={() => {
          if (busy) return;
          setConfirmOpen(false);
        }}
        title={strings.adjustments.bulk.confirmTitle}
        data-testid="adjustments-bulk-confirm-modal"
      >
        <Stack gap="sm">
          <Text size="sm">{strings.adjustments.bulk.confirmBody}</Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => setConfirmOpen(false)}
              disabled={busy}
              data-testid="adjustments-bulk-confirm-cancel"
            >
              {strings.adjustments.bulk.cancel}
            </Button>
            <Button
              onClick={runConfirm}
              loading={busy}
              data-testid="adjustments-bulk-confirm-apply"
            >
              {strings.adjustments.bulk.confirmApply}
            </Button>
          </Group>
        </Stack>
      </Modal>
      {employees.isLoading ? (
        <Group justify="center">
          <Loader />
        </Group>
      ) : null}
    </Stack>
  );
}
