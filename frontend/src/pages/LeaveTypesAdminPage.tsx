import { useState } from "react";
import {
  useInfiniteQuery, useMutation, useQueryClient,
} from "@tanstack/react-query";
import {
  Alert, Badge, Button, Card, Group, Loader, Stack, Table, Tabs, Text,
  Title,
} from "@mantine/core";
import { useMe } from "../auth/useMe";
import {
  fetchLeaveTypesPage,
  deactivateLeaveType,
  reactivateLeaveType,
  type LeaveTypeOut,
} from "../api/leaveTypes";
import { LeaveTypeFormModal } from "../components/Leave/LeaveTypeFormModal";
import { mapLeaveTypeError } from "../components/Leave/LeaveTypeFormModal";

type Tab = "active" | "inactive";

function fmt(s: string | null): string {
  if (s === null) return "—";
  const n = Number(s);
  return Number.isFinite(n) ? n.toFixed(2) : s;
}

export function LeaveTypesAdminPage() {
  const me = useMe();
  const qc = useQueryClient();
  const permissions = me.data?.permissions ?? [];
  const canManage = permissions.includes("user_manage");

  const [tab, setTab] = useState<Tab>("active");
  const [formOpen, setFormOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<LeaveTypeOut | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const q = useInfiniteQuery({
    queryKey: ["leave_types_admin", tab],
    queryFn: ({ pageParam }) =>
      fetchLeaveTypesPage({
        is_active: tab === "active",
        limit: 100,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: canManage,
  });

  const deactMut = useMutation({
    mutationFn: (id: string) => deactivateLeaveType(id),
    onSuccess: (t) => {
      setActionMsg(`Deactivated "${t.name}".`);
      qc.invalidateQueries({ queryKey: ["leave_types_admin"] });
      qc.invalidateQueries({ queryKey: ["leave_types"] });
    },
    onError: (err) => setActionMsg(mapLeaveTypeError(err)),
  });

  const reactMut = useMutation({
    mutationFn: (id: string) => reactivateLeaveType(id),
    onSuccess: (t) => {
      setActionMsg(`Reactivated "${t.name}".`);
      qc.invalidateQueries({ queryKey: ["leave_types_admin"] });
      qc.invalidateQueries({ queryKey: ["leave_types"] });
    },
    onError: (err) => setActionMsg(mapLeaveTypeError(err)),
  });

  if (me.isLoading) {
    return <Loader data-testid="leave-types-admin-loading" />;
  }
  if (!canManage) {
    return (
      <Alert color="yellow" data-testid="leave-types-admin-no-permission">
        You do not have permission to manage leave types.
      </Alert>
    );
  }

  const items = q.data?.pages.flatMap((p) => p.items) ?? [];

  const openCreate = () => {
    setEditTarget(null);
    setFormOpen(true);
  };
  const openEdit = (t: LeaveTypeOut) => {
    setEditTarget(t);
    setFormOpen(true);
  };

  const onDeactivate = (t: LeaveTypeOut) => {
    if (!window.confirm(
      `Deactivate "${t.name}"? Existing balances must not reference this type.`,
    )) return;
    deactMut.mutate(t.id);
  };
  const onReactivate = (t: LeaveTypeOut) => {
    if (!window.confirm(`Reactivate "${t.name}"?`)) return;
    reactMut.mutate(t.id);
  };

  return (
    <Stack gap="md" data-testid="leave-types-admin-page">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Leave Types</Title>
          <Text size="sm" c="dimmed">
            Create, edit and manage leave types for this tenant.
          </Text>
        </div>
        <Button data-testid="leave-types-create" onClick={openCreate}>
          Create leave type
        </Button>
      </Group>

      {actionMsg && (
        <Alert
          color={deactMut.isError || reactMut.isError ? "red" : "green"}
          data-testid="leave-types-action-msg"
          withCloseButton
          onClose={() => setActionMsg(null)}
        >
          {actionMsg}
        </Alert>
      )}

      <Tabs
        value={tab}
        onChange={(v) => setTab((v as Tab) ?? "active")}
        data-testid="leave-types-tabs"
      >
        <Tabs.List>
          <Tabs.Tab value="active" data-testid="leave-types-tab-active">
            Active
          </Tabs.Tab>
          <Tabs.Tab value="inactive" data-testid="leave-types-tab-inactive">
            Inactive
          </Tabs.Tab>
        </Tabs.List>
      </Tabs>

      {q.isLoading && <Loader data-testid="leave-types-table-loading" />}

      {q.isError && (
        <Alert color="red" data-testid="leave-types-admin-error">
          Could not load leave types.
        </Alert>
      )}

      {!q.isLoading && !q.isError && items.length === 0 && (
        <Alert color="blue" data-testid="leave-types-admin-empty">
          No {tab} leave types.
        </Alert>
      )}

      {items.length > 0 && (
        <Card withBorder padding="md">
          <Table data-testid="leave-types-admin-table">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Name</Table.Th>
                <Table.Th>Code</Table.Th>
                <Table.Th>Unit</Table.Th>
                <Table.Th>Paid</Table.Th>
                <Table.Th>Accrual</Table.Th>
                <Table.Th>Amount</Table.Th>
                <Table.Th>Cycle</Table.Th>
                <Table.Th>Chain</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th></Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((t) => (
                <Table.Tr key={t.id} data-testid={`leave-types-row-${t.id}`}>
                  <Table.Td>{t.name}</Table.Td>
                  <Table.Td>{t.code}</Table.Td>
                  <Table.Td>{t.unit}</Table.Td>
                  <Table.Td>{t.paid ? "Yes" : "No"}</Table.Td>
                  <Table.Td>{t.accrual_method}</Table.Td>
                  <Table.Td>{fmt(t.accrual_amount)}</Table.Td>
                  <Table.Td>{t.cycle}</Table.Td>
                  <Table.Td>{t.approval_chain.join(" → ") || "—"}</Table.Td>
                  <Table.Td>
                    <Badge color={t.is_active ? "green" : "gray"}>
                      {t.is_active ? "active" : "inactive"}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs">
                      <Button
                        size="xs"
                        variant="light"
                        data-testid={`leave-types-edit-${t.id}`}
                        onClick={() => openEdit(t)}
                      >
                        Edit
                      </Button>
                      {t.is_active ? (
                        <Button
                          size="xs"
                          variant="light"
                          color="red"
                          loading={deactMut.isPending}
                          data-testid={`leave-types-deactivate-${t.id}`}
                          onClick={() => onDeactivate(t)}
                        >
                          Deactivate
                        </Button>
                      ) : (
                        <Button
                          size="xs"
                          variant="light"
                          color="green"
                          loading={reactMut.isPending}
                          data-testid={`leave-types-reactivate-${t.id}`}
                          onClick={() => onReactivate(t)}
                        >
                          Reactivate
                        </Button>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {q.hasNextPage && (
            <Group justify="center" mt="md">
              <Button
                variant="default"
                data-testid="leave-types-load-more"
                loading={q.isFetchingNextPage}
                onClick={() => q.fetchNextPage()}
              >
                Load more
              </Button>
            </Group>
          )}
        </Card>
      )}

      <LeaveTypeFormModal
        opened={formOpen}
        onClose={() => setFormOpen(false)}
        initialType={editTarget}
        onSuccess={() => {
          setFormOpen(false);
          setActionMsg(
            editTarget ? "Leave type updated." : "Leave type created.",
          );
        }}
      />
    </Stack>
  );
}