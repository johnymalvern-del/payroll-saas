/**
 * DayHistory — per-day correction history section for the day panel.
 *
 * Stage B Batch B. Collapsed by default. When expanded, lists the
 * adjustments (corrections) applied to this (employee, date) from the
 * append-only Adjustment table, newest first. Each row has a summary line
 * plus an expandable "Details" toggle showing the raw old_value / new_value
 * snapshots captured by _apply_adjustment.
 *
 * Read-only. No writes. The endpoint is GET /attendance/adjustments/history
 * permissioned to ATTENDANCE_VIEW; scope is enforced server-side.
 *
 * Data is fetched via fetchAdjustmentHistory(employeeId, workDate) from
 * api/adjustments.ts. React Query caches under
 * ["attendance", "adjustments", "history", employeeId, workDate].
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Accordion,
  Alert,
  Badge,
  Code,
  Group,
  Loader,
  Stack,
  Text,
} from "@mantine/core";
import dayjs from "dayjs";
import {
  fetchAdjustmentHistory,
  type AdjustmentHistoryRow,
} from "../../api/adjustments";
import { strings } from "../../lib/strings";
import { colors } from "../../theme/colors";

type Props = {
  employeeId: string;
  workDate: string;
};

const H = strings.attendance.dayPanel.history;

function snapshotStatus(snapshot: Record<string, unknown> | null): string {
  if (!snapshot) return "—";
  const day = snapshot["day"];
  if (day && typeof day === "object") {
    const s = (day as Record<string, unknown>)["status"];
    if (typeof s === "string" && s) return s;
  }
  const s = snapshot["status"];
  if (typeof s === "string" && s) return s;
  return "—";
}

function summaryChange(row: AdjustmentHistoryRow): string {
  const from = snapshotStatus(row.old_value);
  const to = snapshotStatus(row.new_value);
  return `${from} → ${to}`;
}

function HistoryRow({ row }: { row: AdjustmentHistoryRow }) {
  const [showDetails, setShowDetails] = useState(false);
  const when = dayjs(row.created_at).format("YYYY-MM-DD HH:mm");
  const by = row.created_by_name ?? H.unknownUser;
  return (
    <Stack gap={4} data-testid={`day-history-row-${row.id}`}>
      <Group gap="xs" wrap="wrap">
        <Text size="xs" c="dimmed">
          {when}
        </Text>
        <Badge size="xs" variant="light">
          {row.outcome}
        </Badge>
        <Text size="xs">
          {row.reason_code}
        </Text>
        <Text size="xs" c="dimmed">
          {H.colBy}: {by}
        </Text>
        <Text size="xs" c="dimmed">
          {H.colChange}: {summaryChange(row)}
        </Text>
      </Group>
      {row.note ? (
        <Text size="xs" c="dimmed">
          {H.colNote}: {row.note}
        </Text>
      ) : null}
      <Group gap="xs">
        <Text
          size="xs"
          c="blue"
          style={{ cursor: "pointer", textDecoration: "underline" }}
          onClick={() => setShowDetails((v) => !v)}
          data-testid={`day-history-toggle-${row.id}`}
        >
          {showDetails ? H.hideDetails : H.details}
        </Text>
      </Group>
      {showDetails ? (
        <Stack gap={4} data-testid={`day-history-details-${row.id}`}>
          <Text size="xs" fw={500}>
            {H.oldValue}
          </Text>
          <Code block data-testid={`day-history-old-${row.id}`}>
            {JSON.stringify(row.old_value, null, 2)}
          </Code>
          <Text size="xs" fw={500}>
            {H.newValue}
          </Text>
          <Code block data-testid={`day-history-new-${row.id}`}>
            {JSON.stringify(row.new_value, null, 2)}
          </Code>
        </Stack>
      ) : null}
    </Stack>
  );
}

export function DayHistory({ employeeId, workDate }: Props) {
  const historyQuery = useQuery({
    queryKey: ["attendance", "adjustments", "history", employeeId, workDate],
    queryFn: () => fetchAdjustmentHistory(employeeId, workDate),
    staleTime: 30_000,
  });

  const items = historyQuery.data?.items ?? [];
  const count = items.length;
  const header = count > 0 ? H.titleWithCount(count) : H.title;

  return (
    <Accordion variant="contained" chevronPosition="left">
      <Accordion.Item value="day-history">
        <Accordion.Control data-testid="day-history-toggle">
          {header}
        </Accordion.Control>
        <Accordion.Panel>
          {historyQuery.isLoading ? (
            <Group gap="xs">
              <Loader size="xs" />
              <Text size="sm" c="dimmed">{H.loading}</Text>
            </Group>
          ) : historyQuery.isError ? (
            <Alert color={colors.problem} data-testid="day-history-error">
              {H.error}
            </Alert>
          ) : count === 0 ? (
            <Text size="sm" c="dimmed" data-testid="day-history-empty">
              {H.empty}
            </Text>
          ) : (
            <Stack gap="md" data-testid="day-history-list">
              {items.map((row) => (
                <HistoryRow key={row.id} row={row} />
              ))}
            </Stack>
          )}
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}