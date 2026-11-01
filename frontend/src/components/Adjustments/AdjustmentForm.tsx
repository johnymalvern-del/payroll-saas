import { useState } from "react";
import {
  Alert,
  Button,
  Group,
  Select,
  Stack,
  Textarea,
  TextInput,
} from "@mantine/core";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import {
  ADJUSTMENT_OUTCOMES,
  type AdjustmentOutcome,
} from "../../api/adjustments";
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

  const requiresTimes = outcome === "worked";
  const reasonIsOther = reasonCode.trim().toLowerCase() === "other";

  const submit = () => {
    setError(null);
    if (!reasonCode.trim()) {
      setError(strings.adjustments.reasonRequired);
      return;
    }
    if (requiresTimes && (!timeIn || !timeOut)) {
      setError(strings.adjustments.timesRequired);
      return;
    }
    if (requiresTimes && timeIn && timeOut) {
      const tin = dayjs.tz(`${workDate}T${timeIn}:00`, DEFAULT_SITE_TZ);
      const tout = dayjs.tz(`${workDate}T${timeOut}:00`, DEFAULT_SITE_TZ);
      if (!tin.isValid() || !tout.isValid() || !tout.isAfter(tin)) {
        setError(strings.adjustments.timeOrder);
        return;
      }
    }
    if (reasonIsOther && note.trim().length < 10) {
      setError(strings.adjustments.noteRequiredForOther);
      return;
    }
    onSubmit({
      outcome,
      time_in:
        requiresTimes && timeIn
          ? dayjs.tz(`${workDate}T${timeIn}:00`, DEFAULT_SITE_TZ).toISOString()
          : null,
      time_out:
        requiresTimes && timeOut
          ? dayjs
              .tz(`${workDate}T${timeOut}:00`, DEFAULT_SITE_TZ)
              .toISOString()
          : null,
      reason_code: reasonCode.trim(),
      note: note.trim() ? note.trim() : null,
    });
  };

  return (
    <Stack gap="sm">
      {error ? <Alert color="red">{error}</Alert> : null}
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
        <Group grow>
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
      ) : null}
      <TextInput
        label={strings.adjustments.reasonCode}
        value={reasonCode}
        onChange={(e) => setReasonCode(e.currentTarget.value)}
        description={strings.adjustments.reasonCodeHint}
        required
        data-testid="adj-reason"
      />
      <Textarea
        label={strings.adjustments.note}
        value={note}
        onChange={(e) => setNote(e.currentTarget.value)}
        description={
          reasonIsOther ? strings.adjustments.noteOtherHint : undefined
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
