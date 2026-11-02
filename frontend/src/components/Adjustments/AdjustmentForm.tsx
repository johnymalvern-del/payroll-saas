import { useState } from "react";
import {
  Alert,
  Button,
  Group,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import {
  ADJUSTMENT_OUTCOMES,
  type AdjustmentOutcome,
} from "../../api/adjustments";
import { fetchReasonCodes } from "../../api/reasonCodes";
import { DEFAULT_SITE_TZ } from "../../lib/config";
import { strings } from "../../lib/strings";

dayjs.extend(utc);
dayjs.extend(timezone);

export type AdjustmentFormValues = {
  outcome: AdjustmentOutcome;
  time_in: string | null;
  time_out: string | null;
  reason_code: string;
  note: string | null;
};

type Props = {
  workDate: string;
  initial?: Partial<AdjustmentFormValues>;
  onSubmit: (values: AdjustmentFormValues) => void;
  submitLabel?: string;
  busy?: boolean;
};

function toTimeInput(value: string | null | undefined): string {
  if (!value) return "";
  const d = dayjs(value).tz(DEFAULT_SITE_TZ);
  return d.isValid() ? d.format("HH:mm") : "";
}

function timesCrossMidnight(timeIn: string, timeOut: string): boolean {
  if (!timeIn || !timeOut) return false;
  return timeOut < timeIn;
}

export function AdjustmentForm({
  workDate,
  initial,
  onSubmit,
  submitLabel,
  busy,
}: Props) {
  const [outcome, setOutcome] = useState<AdjustmentOutcome>(
    initial?.outcome ?? "worked",
  );
  const [timeIn, setTimeIn] = useState<string>(toTimeInput(initial?.time_in));
  const [timeOut, setTimeOut] = useState<string>(
    toTimeInput(initial?.time_out),
  );
  const [reasonCode, setReasonCode] = useState<string>(
    initial?.reason_code ?? "",
  );
  const [note, setNote] = useState<string>(initial?.note ?? "");
  const [error, setError] = useState<string | null>(null);

  const codesQuery = useQuery({
    queryKey: ["refs", "reason_codes"],
    queryFn: fetchReasonCodes,
    staleTime: 5 * 60 * 1000,
  });
  const codes = codesQuery.data ?? [];
  const selected = codes.find((c) => c.code === reasonCode) ?? null;
  const requiresNote =
    selected?.requires_note ?? (reasonCode === "other");

  const requiresTimes = outcome === "worked";
  const isNextDay = requiresTimes && timesCrossMidnight(timeIn, timeOut);

  const submit = () => {
    setError(null);
    if (!reasonCode.trim()) {
      setError(strings.adjustments.reasonCodeRequired);
      return;
    }
    if (requiresTimes && (!timeIn || !timeOut)) {
      setError(strings.adjustments.timesRequired);
      return;
    }
    if (requiresNote && note.trim().length < 10) {
      setError(strings.adjustments.noteRequiredForOther);
      return;
    }

    let timeInIso: string | null = null;
    let timeOutIso: string | null = null;
    if (requiresTimes && timeIn && timeOut) {
      const tin = dayjs.tz(`${workDate}T${timeIn}:00`, DEFAULT_SITE_TZ);
      const toutBase = dayjs.tz(`${workDate}T${timeOut}:00`, DEFAULT_SITE_TZ);
      if (!tin.isValid() || !toutBase.isValid()) {
        setError(strings.adjustments.timesRequired);
        return;
      }
      const tout = isNextDay ? toutBase.add(1, "day") : toutBase;
      if (!tout.isAfter(tin)) {
        setError(strings.adjustments.timeOrder);
        return;
      }
      timeInIso = tin.toISOString();
      timeOutIso = tout.toISOString();
    }

    onSubmit({
      outcome,
      time_in: timeInIso,
      time_out: timeOutIso,
      reason_code: reasonCode.trim(),
      note: note.trim() ? note.trim() : null,
    });
  };

  return (
    <Stack gap="sm">
      {error ? <Alert color="red">{error}</Alert> : null}
      {codesQuery.isError ? (
        <Alert color="red" data-testid="adj-reason-error">
          {strings.adjustments.reasonCodeError}
        </Alert>
      ) : null}
      <Select
        label={strings.adjustments.outcome}
        data={ADJUSTMENT_OUTCOMES.map((o) => ({
          value: o,
          label: o.replace(/_/g, " "),
        }))}
        value={outcome}
        onChange={(v) => v && setOutcome(v as AdjustmentOutcome)}
        allowDeselect={false}
        data-testid="adj-outcome"
      />
      {requiresTimes ? (
        <Stack gap={4}>
          <Group grow align="flex-end">
            <TextInput
              label={strings.adjustments.timeIn}
              type="time"
              value={timeIn}
              onChange={(e) => setTimeIn(e.currentTarget.value)}
              data-testid="adj-time-in"
            />
            <TextInput
              label={strings.adjustments.timeOut}
              type="time"
              value={timeOut}
              onChange={(e) => setTimeOut(e.currentTarget.value)}
              data-testid="adj-time-out"
            />
          </Group>
          {isNextDay ? (
            <Text size="xs" c="blue" data-testid="adj-next-day">
              {strings.adjustments.nextDayIndicator}
            </Text>
          ) : null}
        </Stack>
      ) : null}
      <Select
        label={strings.adjustments.reasonCode}
        placeholder={strings.adjustments.selectReasonCode}
        data={codes.map((c) => ({ value: c.code, label: c.label }))}
        value={reasonCode || null}
        onChange={(v) => setReasonCode(v ?? "")}
        required
        disabled={codesQuery.isLoading || codesQuery.isError}
        description={strings.adjustments.reasonCodeHint}
        data-testid="adj-reason"
      />
      <Textarea
        label={strings.adjustments.note}
        value={note}
        onChange={(e) => setNote(e.currentTarget.value)}
        description={
          requiresNote ? strings.adjustments.noteOtherHint : undefined
        }
        minRows={2}
        data-testid="adj-note"
      />
      <Group justify="flex-end">
        <Button onClick={submit} loading={busy} data-testid="adj-submit">
          {submitLabel ?? strings.adjustments.submit}
        </Button>
      </Group>
    </Stack>
  );
}
