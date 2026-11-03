import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Drawer,
  Group,
  Loader,
  Paper,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import {
  downloadMyPayslipPdf,
  fetchMyPayslip,
  fetchMyPayslips,
  OwnPayslipsApiError,
  type PayslipMeRow,
} from "../api/ownPayslips";
import { useMe } from "../auth/useMe";
import { mapErrorCode } from "../api/errors";
import { strings } from "../lib/strings";

const PAGE_SIZE = 100;

function fmtDate(d: string | null | undefined): string {
  return d ? dayjs(d).format("YYYY-MM-DD") : "—";
}

function fmtDateTime(d: string | null | undefined): string {
  return d ? dayjs(d).format("YYYY-MM-DD HH:mm") : "—";
}

function mapErr(err: unknown): string {
  if (err instanceof OwnPayslipsApiError) {
    if (err.code === "forbidden") return strings.payslips.auditorNotAllowed;
    if (err.code === "no_employee_record") return strings.payslips.error;
    return mapErrorCode(err.code);
  }
  return strings.genericError;
}

type DetailTarget = { id: string; key: string } | null;

export function OwnPayslipsPage() {
  const me = useMe();
  const [detail, setDetail] = useState<DetailTarget>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [pdfBusy, setPdfBusy] = useState<string | null>(null);

  const isAuditor = me.data?.role === "auditor";

  const list = useInfiniteQuery({
    queryKey: ["my_payslips"],
    queryFn: ({ pageParam }) =>
      fetchMyPayslips({ cursor: pageParam, limit: PAGE_SIZE }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: me.isSuccess && !isAuditor,
  });

  const items: PayslipMeRow[] = list.data?.pages.flatMap((p) => p.items) ?? [];

  const entry = useQuery({
    queryKey: ["my_payslip", detail?.id],
    queryFn: () => fetchMyPayslip(detail!.id),
    enabled: !!detail?.id,
  });

  const onDownload = async (id: string) => {
    setPdfBusy(id);
    setPdfError(null);
    try {
      await downloadMyPayslipPdf(id);
    } catch (err) {
      setPdfError(mapErr(err));
    } finally {
      setPdfBusy(null);
    }
  };

  if (me.isLoading) {
    return (
      <Group justify="center" p="xl">
        <Loader />
      </Group>
    );
  }

  if (isAuditor) {
    return (
      <Stack gap="md">
        <Title order={2}>{strings.payslips.title}</Title>
        <Alert color="blue" data-testid="payslips-auditor-notice">
          {strings.payslips.auditorNotAllowed}
        </Alert>
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      <Title order={2}>{strings.payslips.title}</Title>
      {pdfError ? (
        <Alert
          color="red"
          withCloseButton
          onClose={() => setPdfError(null)}
          data-testid="payslips-pdf-error"
        >
          {pdfError}
        </Alert>
      ) : null}
      <Paper withBorder p="md">
        {list.isPending ? (
          <Group justify="center" p="xl">
            <Loader />
          </Group>
        ) : list.isError ? (
          <Group justify="space-between" align="center">
            <Text c="red" size="sm" data-testid="payslips-error">
              {mapErr(list.error)}
            </Text>
            <Button
              size="xs"
              variant="default"
              onClick={() => list.refetch()}
              data-testid="payslips-retry"
            >
              {strings.common.retry}
            </Button>
          </Group>
        ) : items.length === 0 ? (
          <Text c="dimmed">{strings.payslips.empty}</Text>
        ) : (
          <Table.ScrollContainer minWidth={700}>
            <Table striped withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{strings.payslips.colPeriod}</Table.Th>
                  <Table.Th>{strings.payslips.colPayDate}</Table.Th>
                  <Table.Th>{strings.payslips.colStatus}</Table.Th>
                  <Table.Th>{strings.payslips.colGross}</Table.Th>
                  <Table.Th>{strings.payslips.colNet}</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {items.map((p) => (
                  <Table.Tr key={p.id} data-testid={`payslip-row-${p.id}`}>
                    <Table.Td>{p.period_key}</Table.Td>
                    <Table.Td>{fmtDate(p.pay_date)}</Table.Td>
                    <Table.Td>{p.status}</Table.Td>
                    <Table.Td>{p.gross}</Table.Td>
                    <Table.Td>{p.net}</Table.Td>
                    <Table.Td>
                      <Group gap="xs">
                        <Button
                          size="xs"
                          variant="default"
                          onClick={() =>
                            setDetail({ id: p.id, key: p.period_key })
                          }
                          data-testid={`payslip-view-${p.id}`}
                        >
                          {strings.payslips.viewDetail}
                        </Button>
                        <Button
                          size="xs"
                          variant="default"
                          onClick={() => onDownload(p.id)}
                          loading={pdfBusy === p.id}
                          data-testid={`payslip-download-${p.id}`}
                        >
                          {strings.payslips.downloadPdf}
                        </Button>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Paper>
      {list.hasNextPage ? (
        <Group justify="center">
          <Button
            variant="default"
            onClick={() => list.fetchNextPage()}
            loading={list.isFetchingNextPage}
            data-testid="payslips-load-more"
          >
            {strings.payslips.loadMore}
          </Button>
        </Group>
      ) : null}

      <Drawer
        opened={detail !== null}
        onClose={() => setDetail(null)}
        position="right"
        size="lg"
        title={
          detail
            ? strings.payslips.detailTitle(detail.key)
            : strings.payslips.title
        }
        data-testid="payslip-drawer"
      >
        {entry.isLoading ? (
          <Group justify="center" p="xl">
            <Loader />
          </Group>
        ) : entry.isError || !entry.data ? (
          <Alert color="red" data-testid="payslip-detail-error">
            {strings.payslips.detailError}
          </Alert>
        ) : (
          <Stack gap="sm" data-testid="payslip-detail">
            <Row label={strings.payslips.fieldRevision} value={String(entry.data.revision)} />
            <Row label={strings.payslips.fieldStatus} value={entry.data.status} />
            <Row label={strings.payslips.fieldGross} value={entry.data.gross} />
            <Row label={strings.payslips.fieldPreTax} value={entry.data.pre_tax_deductions} />
            <Row label={strings.payslips.fieldTaxable} value={entry.data.taxable_income} />
            <Row label={strings.payslips.fieldPaye} value={entry.data.paye} />
            <Row label={strings.payslips.fieldUifEmployee} value={entry.data.uif_employee} />
            <Row label={strings.payslips.fieldUifEmployer} value={entry.data.uif_employer} />
            <Row label={strings.payslips.fieldSdl} value={entry.data.sdl} />
            <Row label={strings.payslips.fieldOther} value={entry.data.other_deductions} />
            <Row label={strings.payslips.fieldReimbursements} value={entry.data.reimbursements} />
            <Row label={strings.payslips.fieldNet} value={entry.data.net} />
            <Row label={strings.payslips.fieldComputedAt} value={fmtDateTime(entry.data.computed_at)} />
            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={() => detail && onDownload(detail.id)}
                loading={pdfBusy === detail?.id}
                data-testid="payslip-detail-download"
              >
                {strings.payslips.downloadPdf}
              </Button>
              <Button onClick={() => setDetail(null)} data-testid="payslip-detail-close">
                {strings.payslips.close}
              </Button>
            </Group>
          </Stack>
        )}
      </Drawer>
    </Stack>
  );
}

function Row(props: { label: string; value: string }) {
  return (
    <Group justify="space-between">
      <Text size="xs" c="dimmed">
        {props.label}
      </Text>
      <Text size="sm">{props.value}</Text>
    </Group>
  );
}
