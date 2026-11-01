import { Badge, Button, Card, Group, Stack, Text } from "@mantine/core";
import dayjs from "dayjs";
import type { ExceptionRow } from "../../api/exceptions";
import { suggestionSummary } from "../../lib/exceptionSummary";
import { exceptionTypeLabel, strings } from "../../lib/strings";

type Props = {
  exception: ExceptionRow;
  employeeName: string;
  employeeCode: string;
  onApplySuggestion: () => void;
  onCustom: () => void;
  onDismiss: () => void;
  busy?: boolean;
};

function typeColor(type: string): string {
  if (type.includes("missing")) return "orange";
  if (type.includes("overtime") || type.includes("long")) return "red";
  if (type.includes("confidence") || type.includes("duplicate")) return "yellow";
  return "blue";
}

export function ExceptionCard({
  exception,
  employeeName,
  employeeCode,
  onApplySuggestion,
  onCustom,
  onDismiss,
  busy,
}: Props) {
  const summary = suggestionSummary(exception.suggested_fix);
  return (
    <Card withBorder padding="md" data-testid={`exception-${exception.id}`}>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={4}>
          <Group gap="sm">
            <Badge
              color={typeColor(exception.type)}
              variant="light"
              data-testid={`type-badge-${exception.id}`}
            >
              {exceptionTypeLabel(exception.type)}
            </Badge>
            <Text size="sm" c="dimmed">
              {dayjs(exception.work_date).format("DD MMM YYYY")}
            </Text>
          </Group>
          <Text size="sm" fw={500}>
            {employeeName}
            {employeeCode ? ` (${employeeCode})` : ""}
          </Text>
          {summary ? (
            <Text size="xs" c="dimmed">
              {strings.exceptions.suggestedLabel} {summary}
            </Text>
          ) : null}
        </Stack>
        <Group gap="xs" wrap="nowrap">
          {summary ? (
            <Button
              size="xs"
              onClick={onApplySuggestion}
              loading={busy}
              data-testid={`apply-${exception.id}`}
            >
              {strings.exceptions.applyButton}
            </Button>
          ) : null}
          <Button
            size="xs"
            variant="default"
            onClick={onCustom}
            data-testid={`custom-${exception.id}`}
          >
            {strings.exceptions.customButton}
          </Button>
          <Button
            size="xs"
            variant="default"
            onClick={onDismiss}
            data-testid={`dismiss-${exception.id}`}
          >
            {strings.exceptions.dismissButton}
          </Button>
        </Group>
      </Group>
    </Card>
  );
}
