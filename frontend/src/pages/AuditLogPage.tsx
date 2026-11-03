import { useMemo, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Drawer,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import {
  AuditLogApiError,
  fetchAuditLog,
  fetchAuditLogEntry,
  type AuditLogFilters,
  type AuditLogOut,
} from "../api/auditLog";
import { mapErrorCode } from "../api/errors";
import { strings } from "../lib/strings";

const PAGE_SIZE = 100;

function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "—";
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return dayjs(iso).format("YYYY-MM-DD HH:mm:ss");
}

function fmtJson(v: unknown): string {
  if (v === null || v === undefined) return strings.auditLog.fieldEmpty;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

type RawFilters = {
  occurred_from: string;
  occurred_to: string;
  entity_type: string;
  entity_id: string;
  action: string;
  actor_role: string;
  actor_user_id: string;
  request_id: string;
  reason: string;
};

const BLANK: RawFilters = {
  occurred_from: "",
  occurred_to: "",
  entity_type: "",
  entity_id: "",
  action: "",
  actor_role: "",
  actor_user_id: "",
  request_id: "",
  reason: "",
};

function toApiFilters(f: RawFilters): AuditLogFilters {
  const out: AuditLogFilters = {};
  if (f.occurred_from) {
    out.occurred_from = dayjs(f.occurred_from).startOf("day").toISOString();
  }
  if (f.occurred_to) {
    out.occurred_to = dayjs(f.occurred_to).endOf("day").toISOString();
  }
  if (f.entity_type.trim()) out.entity_type = f.entity_type.trim();
  if (f.entity_id.trim()) out.entity_id = f.entity_id.trim();
  if (f.action.trim()) out.action = f.action.trim();
  if (f.actor_role.trim()) out.actor_role = f.actor_role.trim();
  if (f.actor_user_id.trim()) out.actor_user_id = f.actor_user_id.trim();
  if (f.request_id.trim()) out.request_id = f.request_id.trim();
  if (f.reason.trim()) out.reason = f.reason.trim();
  return out;
}

export function AuditLogPage() {
  const [raw, setRaw] = useState<RawFilters>(BLANK);
  const [committed, setCommitted] = useState<RawFilters>(BLANK);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const apiFilters = useMemo(() => toApiFilters(committed), [committed]);

  const log = useInfiniteQuery({
    queryKey: ["audit_log", apiFilters],
    queryFn: ({ pageParam }) =>
      fetchAuditLog({
        filters: apiFilters,
        cursor: pageParam,
        limit: PAGE_SIZE,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const items: AuditLogOut[] =
    log.data?.pages.flatMap((p) => p.items) ?? [];

  const rangeNotice = useMemo(() => {
    const first = log.data?.pages[0];
    if (!first) return null;
    return strings.auditLog.rangeNotice(
      dayjs(first.occurred_from_applied).format("YYYY-MM-DD HH:mm"),
      dayjs(first.occurred_to_applied).format("YYYY-MM-DD HH:mm"),
    );
  }, [log.data]);

  const detail = useQuery({
    queryKey: ["audit_entry", detailId],
    queryFn: () => fetchAuditLogEntry(detailId!),
    enabled: !!detailId,
  });

  const set = <K extends keyof RawFilters>(k: K, v: RawFilters[K]) =>
    setRaw((prev) => ({ ...prev, [k]: v }));

  const applyFilters = () => {
    if (
      raw.occurred_from &&
      raw.occurred_to &&
      dayjs(raw.occurred_to).isBefore(dayjs(raw.occurred_from), "day")
    ) {
      setFilterError(strings.auditLog.errInvalidRange);
      return;
    }
    setFilterError(null);
    setCommitted(raw);
  };

  const clearFilters = () => {
    setFilterError(null);
    setRaw(BLANK);
    setCommitted(BLANK);
  };

  return (
    <Stack gap="md">
      <Title order={2}>{strings.auditLog.title}</Title>

      {log.isError ? (
        <Alert color="red" data-testid="audit-log-error">
          {log.error instanceof AuditLogApiError
            ? mapErrorCode(log.error.code)
            : strings.auditLog.error}
        </Alert>
      ) : null}

      <Paper withBorder p="md">
        <Stack gap="sm">
          <Text fw={600} size="sm">
            {strings.auditLog.filtersHeader}
          </Text>
          {filterError ? (
            <Alert color="red" data-testid="audit-log-filter-error">
              {filterError}
            </Alert>
          ) : null}
          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
            <TextInput
              label={strings.auditLog.occurredFrom}
              type="date"
              value={raw.occurred_from}
              onChange={(e) => set("occurred_from", e.currentTarget.value)}
              data-testid="audit-log-from"
            />
            <TextInput
              label={strings.auditLog.occurredTo}
              type="date"
              value={raw.occurred_to}
              onChange={(e) => set("occurred_to", e.currentTarget.value)}
              data-testid="audit-log-to"
            />
            <TextInput
              label={strings.auditLog.entityType}
              value={raw.entity_type}
              onChange={(e) => set("entity_type", e.currentTarget.value)}
              data-testid="audit-log-entity-type"
            />
            <TextInput
              label={strings.auditLog.entityId}
              value={raw.entity_id}
              onChange={(e) => set("entity_id", e.currentTarget.value)}
              data-testid="audit-log-entity-id"
            />
            <TextInput
              label={strings.auditLog.action}
              value={raw.action}
              onChange={(e) => set("action", e.currentTarget.value)}
              data-testid="audit-log-action"
            />
            <TextInput
              label={strings.auditLog.actorRole}
              value={raw.actor_role}
              onChange={(e) => set("actor_role", e.currentTarget.value)}
              data-testid="audit-log-actor-role"
            />
            <TextInput
              label={strings.auditLog.actorUserId}
              value={raw.actor_user_id}
              onChange={(e) => set("actor_user_id", e.currentTarget.value)}
              data-testid="audit-log-actor-user-id"
            />
            <TextInput
              label={strings.auditLog.requestId}
              value={raw.request_id}
              onChange={(e) => set("request_id", e.currentTarget.value)}
              data-testid="audit-log-request-id"
            />
            <TextInput
              label={strings.auditLog.reason}
              value={raw.reason}
              onChange={(e) => set("reason", e.currentTarget.value)}
              data-testid="audit-log-reason"
            />
          </SimpleGrid>
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={clearFilters}
              data-testid="audit-log-clear"
            >
              {strings.auditLog.clearFilters}
            </Button>
            <Button onClick={applyFilters} data-testid="audit-log-apply">
              {strings.common.confirm}
            </Button>
          </Group>
          {rangeNotice ? (
            <Text size="xs" c="dimmed" data-testid="audit-log-range">
              {rangeNotice}
            </Text>
          ) : null}
        </Stack>
      </Paper>

      <Paper withBorder p="md">
        {log.isPending ? (
          <Group justify="center" p="xl">
            <Loader />
          </Group>
        ) : log.isError ? (
          <Group justify="space-between" align="center">
            <Text c="red" size="sm" data-testid="audit-log-load-error">
              {strings.auditLog.error}
            </Text>
            <Button
              size="xs"
              variant="default"
              onClick={() => log.refetch()}
              data-testid="audit-log-retry"
            >
              {strings.common.retry}
            </Button>
          </Group>
        ) : items.length === 0 ? (
          <Text c="dimmed">{strings.auditLog.empty}</Text>
        ) : (
          <Table.ScrollContainer minWidth={900}>
            <Table striped withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{strings.auditLog.fieldOccurredAt}</Table.Th>
                  <Table.Th>{strings.auditLog.fieldActorRole}</Table.Th>
                  <Table.Th>{strings.auditLog.fieldAction}</Table.Th>
                  <Table.Th>{strings.auditLog.fieldEntityType}</Table.Th>
                  <Table.Th>{strings.auditLog.fieldEntityId}</Table.Th>
                  <Table.Th>{strings.auditLog.fieldRequestId}</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {items.map((row) => (
                  <Table.Tr
                    key={row.id}
                    data-testid={`audit-log-row-${row.id}`}
                  >
                    <Table.Td>{fmtDateTime(row.occurred_at)}</Table.Td>
                    <Table.Td>{row.actor_role ?? "—"}</Table.Td>
                    <Table.Td>{row.action}</Table.Td>
                    <Table.Td>{row.entity_type}</Table.Td>
                    <Table.Td>{shortId(row.entity_id)}</Table.Td>
                    <Table.Td>{shortId(row.request_id)}</Table.Td>
                    <Table.Td>
                      <Button
                        size="xs"
                        variant="default"
                        onClick={() => setDetailId(row.id)}
                        data-testid={`audit-log-view-${row.id}`}
                      >
                        {strings.auditLog.viewDetail}
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Paper>

      {log.hasNextPage ? (
        <Group justify="center">
          <Button
            variant="default"
            onClick={() => log.fetchNextPage()}
            loading={log.isFetchingNextPage}
            data-testid="audit-log-load-more"
          >
            {strings.auditLog.loadMore}
          </Button>
        </Group>
      ) : null}

      <Drawer
        opened={detailId !== null}
        onClose={() => setDetailId(null)}
        position="right"
        size="lg"
        title={strings.auditLog.detailTitle}
        data-testid="audit-log-drawer"
      >
        {detail.isLoading ? (
          <Group justify="center" p="xl">
            <Loader />
          </Group>
        ) : detail.isError || !detail.data ? (
          <Alert color="red" data-testid="audit-log-detail-error">
            {strings.auditLog.detailError}
          </Alert>
        ) : (
          <Stack gap="sm" data-testid="audit-log-detail">
            <Field
              label={strings.auditLog.fieldOccurredAt}
              value={fmtDateTime(detail.data.occurred_at)}
            />
            <Field
              label={strings.auditLog.fieldActorUserId}
              value={detail.data.actor_user_id ?? strings.auditLog.fieldEmpty}
            />
            <Field
              label={strings.auditLog.fieldActorRole}
              value={detail.data.actor_role ?? strings.auditLog.fieldEmpty}
            />
            <Field
              label={strings.auditLog.fieldEntityType}
              value={detail.data.entity_type}
            />
            <Field
              label={strings.auditLog.fieldEntityId}
              value={detail.data.entity_id ?? strings.auditLog.fieldEmpty}
            />
            <Field
              label={strings.auditLog.fieldAction}
              value={detail.data.action}
            />
            <Field
              label={strings.auditLog.fieldReason}
              value={detail.data.reason ?? strings.auditLog.fieldEmpty}
            />
            <Field
              label={strings.auditLog.fieldIpAddress}
              value={detail.data.ip_address ?? strings.auditLog.fieldEmpty}
            />
            <Field
              label={strings.auditLog.fieldRequestId}
              value={detail.data.request_id ?? strings.auditLog.fieldEmpty}
            />
            <Field
              label={strings.auditLog.fieldOldValue}
              value={fmtJson(detail.data.old_value)}
              multiline
            />
            <Field
              label={strings.auditLog.fieldNewValue}
              value={fmtJson(detail.data.new_value)}
              multiline
            />
          </Stack>
        )}
      </Drawer>
    </Stack>
  );
}

function Field(props: { label: string; value: string; multiline?: boolean }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed">
        {props.label}
      </Text>
      <Text
        size="sm"
        style={
          props.multiline
            ? { whiteSpace: "pre-wrap", fontFamily: "monospace" }
            : undefined
        }
      >
        {props.value}
      </Text>
    </Stack>
  );
}
