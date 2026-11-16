/**
 * DayCorrection — the correction workflow for a single attendance day.
 *
 * Stage B Batch 1, D3=b (two-step review):
 *   1. editing   — user fills AdjustmentForm
 *   2. reviewing — user sees a summary, clicks Back or Save
 *   3. saving    — Save calls POST /attendance/adjustments
 *   4. success   — green alert, onSaved(result) fires (DayPanel uses
 *                 onSaved to invalidate queries)
 *
 * Locked state (D2=b):
 *   If dayLocked (AttendanceDay.locked) or periodLocked
 *   (PayPeriod.status == "locked"), the accordion header is disabled and
 *   shows the correct message; no form renders. This means HR does not
 *   submit a correction that the Stage A backend guard would reject with
 *   409 day_locked — the UI states the reason up front.
 *
 * What this component does NOT do:
 *   - It does not fetch reason codes. AdjustmentForm owns that.
 *   - It does not invalidate React Query caches. DayPanel does, via
 *     onSaved. This keeps the invalidation policy in the page container.
 *   - It does not mutate AdjustmentForm. The existing form is embedded
 *     as-is; the two-step review wraps it in this component.
 */
import { useState } from "react";
import {
  Alert,
  Button,
  Group,
  Stack,
  Text,
  Accordion,
} from "@mantine/core";
import {
  createAdjustment,
  type AdjustmentResult,
} from "../../api/adjustments";
import { mapErrorCode } from "../../api/errors";
import {
  AdjustmentForm,
  type AdjustmentFormValues,
} from "../Adjustments/AdjustmentForm";
import { fetchReasonCodes, type ReasonCode } from "../../api/reasonCodes";
import { useQuery } from "@tanstack/react-query";
import { strings } from "../../lib/strings";
import { colors } from "../../theme/colors";

type Props = {
  employeeId: string;
  workDate: string;
  /** AttendanceDay.locked from the fetchDay payload. */
  dayLocked: boolean;
  /** PayPeriod.status == "locked" for this day, from the fetchDay payload. */
  periodLocked: boolean;
  /** Called once on successful save with the AdjustmentResult. */
  onSaved: (result: AdjustmentResult) => void;
};

type Phase = "editing" | "reviewing" | "saving" | "success";

const S = strings.attendance.dayPanel;

export function DayCorrection({
  employeeId,
  workDate,
  dayLocked,
  periodLocked,
  onSaved,
}: Props) {
  const locked = dayLocked || periodLocked;
  const lockedMessage = periodLocked
    ? S.correctLockedPeriod
    : S.correctLockedDay;

  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>("editing");
  const [values, setValues] = useState<AdjustmentFormValues | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedReasonLabel, setSavedReasonLabel] = useState<string | null>(null);

  // Fetch reason codes here only to translate the reason code to a
  // human label for the review and success messages. AdjustmentForm
  // fetches the same endpoint independently; both requests share the
  // same React Query cache entry ["refs","reason_codes"].
  const codesQuery = useQuery({
    queryKey: ["refs", "reason_codes"],
    queryFn: fetchReasonCodes,
    staleTime: 5 * 60 * 1000,
  });
  const codes: ReasonCode[] = codesQuery.data ?? [];
  const reasonLabelFor = (code: string): string => {
    const hit = codes.find((c) => c.code === code);
    return hit ? hit.label : code;
  };

  const reset = () => {
    setPhase("editing");
    setValues(null);
    setError(null);
    setSavedReasonLabel(null);
  };

  const handleFormSubmit = (v: AdjustmentFormValues) => {
    setValues(v);
    setPhase("reviewing");
    setError(null);
  };

  const handleBack = () => {
    setPhase("editing");
    setError(null);
  };

  const handleSave = async () => {
    if (!values) return;
    setPhase("saving");
    setError(null);
    try {
      const result = await createAdjustment({
        employee_id: employeeId,
        work_date: workDate,
        outcome: values.outcome,
        time_in: values.time_in,
        time_out: values.time_out,
        reason_code: values.reason_code,
        note: values.note,
      });
      setSavedReasonLabel(reasonLabelFor(values.reason_code));
      setPhase("success");
      onSaved(result);
    } catch (err) {
      // adjustments.ts throws Error(message) where message is the
      // backend's detail.error.code or "http_<status>". We map it to a
      // user-facing message via mapErrorCode, falling back to the
      // generic correction error from strings.
      const code =
        err instanceof Error ? err.message : "http_error";
      setError(mapErrorCode(code, S.correctErrorGeneric));
      setPhase("reviewing");
    }
  };

  return (
    <Accordion
      variant="contained"
      chevronPosition="left"
      value={open ? "day-correction" : null}
      onChange={(v) => {
        if (locked) return;
        const nowOpen = v === "day-correction";
        setOpen(nowOpen);
        if (!nowOpen) reset();
      }}
    >
      <Accordion.Item value="day-correction">
        <Accordion.Control
          disabled={locked}
          data-testid="day-correction-toggle"
        >
          {S.correctThisDay}
        </Accordion.Control>
        <Accordion.Panel>
          {locked ? (
            <Alert
              color={colors.inactive}
              data-testid="day-correction-locked-alert"
            >
              {lockedMessage}
            </Alert>
          ) : phase === "success" ? (
            <Alert color={colors.approved} data-testid="day-correction-success">
              {savedReasonLabel
                ? S.correctSavedFor(savedReasonLabel)
                : S.correctSaveSuccess}
            </Alert>
          ) : phase === "editing" ? (
            <Stack gap="sm">
              <AdjustmentForm
                workDate={workDate}
                onSubmit={handleFormSubmit}
                submitLabel={S.correctSave}
              />
            </Stack>
          ) : (
            <Stack gap="sm" data-testid="day-correction-review">
              <Text size="sm" fw={600}>{S.correctConfirmTitle}</Text>
              <Text size="sm" c="dimmed">{S.correctConfirmBody}</Text>
              {values ? (
                <Stack gap={4}>
                  <Text size="sm">
                    <strong>{strings.adjustments.outcome}:</strong>{" "}
                    {values.outcome.replace(/_/g, " ")}
                  </Text>
                  {values.time_in || values.time_out ? (
                    <Text size="sm">
                      <strong>{strings.adjustments.timeIn}:</strong>{" "}
                      {values.time_in ?? "—"} ·{" "}
                      <strong>{strings.adjustments.timeOut}:</strong>{" "}
                      {values.time_out ?? "—"}
                    </Text>
                  ) : null}
                  <Text size="sm">
                    <strong>{strings.adjustments.reasonCode}:</strong>{" "}
                    {reasonLabelFor(values.reason_code)}
                  </Text>
                  {values.note ? (
                    <Text size="sm">
                      <strong>{strings.adjustments.note}:</strong>{" "}
                      {values.note}
                    </Text>
                  ) : null}
                </Stack>
              ) : null}
              {error ? (
                <Alert color={colors.problem} data-testid="day-correction-error">
                  {error}
                </Alert>
              ) : null}
              <Group justify="flex-end">
                <Button
                  variant="default"
                  onClick={handleBack}
                  disabled={phase === "saving"}
                  data-testid="day-correction-back"
                >
                  {S.correctBack}
                </Button>
                <Button
                  onClick={handleSave}
                  loading={phase === "saving"}
                  disabled={phase === "saving"}
                  data-testid="day-correction-save"
                >
                  {S.correctSave}
                </Button>
              </Group>
            </Stack>
          )}
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}