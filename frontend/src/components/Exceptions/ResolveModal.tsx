import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Group,
  Modal,
  SegmentedControl,
  Stack,
  Textarea,
} from "@mantine/core";
import {
  AdjustmentForm,
  type AdjustmentFormValues,
} from "../Adjustments/AdjustmentForm";
import type { ExceptionRow, ResolveRequest } from "../../api/exceptions";
import { strings } from "../../lib/strings";

type Action = "custom" | "dismiss";

type Props = {
  opened: boolean;
  exception: ExceptionRow | null;
  initialAction: Action;
  onClose: () => void;
  onResolve: (req: ResolveRequest) => void;
  busy?: boolean;
  serverError?: string | null;
};

export function ResolveModal({
  opened,
  exception,
  initialAction,
  onClose,
  onResolve,
  busy,
  serverError,
}: Props) {
  const [action, setAction] = useState<Action>(initialAction);
  const [note, setNote] = useState<string>("");
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    setAction(initialAction);
    setNote("");
    setLocalError(null);
  }, [initialAction, exception?.id]);

  if (!exception) return null;

  const initialCustom: Partial<AdjustmentFormValues> = {
    outcome:
      (exception.suggested_fix.outcome as AdjustmentFormValues["outcome"]) ??
      "worked",
    time_in: (exception.suggested_fix.time_in as string) ?? null,
    time_out: (exception.suggested_fix.time_out as string) ?? null,
    reason_code:
      (exception.suggested_fix.reason_code as string) ?? exception.type,
    note: (exception.suggested_fix.note as string) ?? null,
  };

  const submitDismiss = () => {
    setLocalError(null);
    if (note.trim().length < 3) {
      setLocalError(strings.exceptions.dismissNoteRequired);
      return;
    }
    onResolve({
      action: "dismiss",
      custom_adjustment: null,
      note: note.trim(),
    });
  };

  const submitCustom = (values: AdjustmentFormValues) => {
    onResolve({
      action: "custom",
      custom_adjustment: {
        outcome: values.outcome,
        time_in: values.time_in,
        time_out: values.time_out,
        reason_code: values.reason_code,
        note: values.note,
      },
      note: null,
    });
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={strings.exceptions.resolveTitle}
      size="lg"
    >
      <Stack gap="md">
        <SegmentedControl
          value={action}
          onChange={(v) => setAction(v as Action)}
          data={[
            { label: strings.exceptions.customAction, value: "custom" },
            { label: strings.exceptions.dismissAction, value: "dismiss" },
          ]}
        />
        {serverError ? <Alert color="red">{serverError}</Alert> : null}
        {localError ? <Alert color="red">{localError}</Alert> : null}
        {action === "custom" ? (
          <AdjustmentForm
            workDate={exception.work_date}
            initial={initialCustom}
            onSubmit={submitCustom}
            busy={busy}
          />
        ) : (
          <Stack gap="sm">
            <Textarea
              label={strings.exceptions.dismissNote}
              value={note}
              onChange={(e) => setNote(e.currentTarget.value)}
              minRows={3}
              data-testid="dismiss-note"
            />
            <Group justify="flex-end">
              <Button
                onClick={submitDismiss}
                loading={busy}
                data-testid="dismiss-submit"
              >
                {strings.exceptions.dismissSubmit}
              </Button>
            </Group>
          </Stack>
        )}
      </Stack>
    </Modal>
  );
}
