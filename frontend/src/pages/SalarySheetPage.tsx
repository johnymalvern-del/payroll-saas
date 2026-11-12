import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import {
  fetchPayPeriod,
  fetchSalarySheet,
  PayPeriodsApiError,
  type SalarySheetRow,
} from "../api/payPeriods";
import { mapErrorCode } from "../api/errors";
import { strings } from "../lib/strings";
import { colors } from "../theme/colors";

const PAGE_SIZE = 100;
const SEARCH_DEBOUNCE_MS = 300;

function localDate(d: string): string {
  return dayjs(d).format("DD MMM YYYY");
}

function csvEscape(v: string): string {
  if (v.includes(",") || v.includes('"') || v.includes("\n")) {
    return `"${v.replace(/"/g, '""')}"`;
  }
  return v;
}

function exportCsv(rows: SalarySheetRow[], periodKey: string): void {
  const headers = [
    "Code",
    "Name",
    "Basic earnings",
    "Additional earnings",
    "Gross",
    "Pre-tax deductions",
    "Taxable income",
    "PAYE",
    "UIF (employee)",
    "UIF (employer)",
    "SDL",
    "Other deductions",
    "Reimbursements",
    "Net",
  ];
  const lines = [headers.join(",")];
  for (const r of rows) {
    const cells = [
      r.employee_code,
      r.employee_name,
      r.basic_earnings,
      r.additional_earnings,
      r.gross,
      r.pre_tax_deductions,
      r.taxable_income,
      r.paye,
      r.uif_employee,
      r.uif_employer,
      r.sdl,
      r.other_deductions,
      r.reimbursements,
      r.net,
    ].map(csvEscape);
    lines.push(cells.join(","));
  }
  const blob = new Blob([lines.join("\n")], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `salary-sheet-${periodKey}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function SalarySheetPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [searchInput, setSearchInput] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setQ(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [searchInput]);

  const periodQuery = useQuery({
    queryKey: ["pay_period", id],
    queryFn: () => fetchPayPeriod(id!),
    enabled: !!id,
  });

  const sheetQuery = useInfiniteQuery({
    queryKey: ["salary_sheet", id, q],
    queryFn: ({ pageParam }) =>
      fetchSalarySheet({
        periodId: id!,
        q: q || undefined,
        cursor: pageParam ?? undefined,
        limit: PAGE_SIZE,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: !!id,
  });

  const items: SalarySheetRow[] = useMemo(
    () => sheetQuery.data?.pages.flatMap((p) => p.items) ?? [],
    [sheetQuery.data],
  );
  const head = sheetQuery.data?.pages[0] ?? null;

  if (!id) {
    return <Text c="red">Missing period id.</Text>;
  }

  if (periodQuery.isLoading) {
    return (
      <Group justify="center" p="xl">
        <Loader />
      </Group>
    );
  }

  if (periodQuery.isError || !periodQuery.data) {
    return (
      <Alert color={colors.problem} data-testid="salary-sheet-error">
        {mapErrorCode(
          periodQuery.error instanceof PayPeriodsApiError
            ? periodQuery.error.code
            : "unknown",
        )}
      </Alert>
    );
  }

  const period = periodQuery.data;

  const onExportCsv = () => {
    if (items.length === 0) return;
    exportCsv(items, period.period_key);
  };

  return (
    <Stack gap="md" data-testid="salary-sheet-page">
      <Group justify="space-between" align="center">
        <Group gap="sm">
          <Button
            variant="default"
            onClick={() => navigate(`/payroll/pay-periods/${id}`)}
            data-testid="salary-sheet-back"
          >
            ←
          </Button>
          <Title order={2}>
            Salary Sheet — {period.period_key}
          </Title>
          <Badge
            color={period.status === "locked" ? "gray" : "green"}
            variant="light"
          >
            {period.status}
          </Badge>
        </Group>
      </Group>

      <Paper withBorder p="md">
        <Group gap="lg">
          <Text size="sm">
            {localDate(period.start_date)} → {localDate(period.end_date)}
          </Text>
          <Text size="sm">
            {strings.payPeriods.rowPayDate}: {localDate(period.pay_date)}
          </Text>
        </Group>
      </Paper>

      {head?.figures_state === "finalised" ? (
        <Alert color="green" data-testid="salary-sheet-finalised-banner">
          Finalised figures — locked period, read-only.
        </Alert>
      ) : head?.figures_state === "preview" ? (
        <Alert color="blue" data-testid="salary-sheet-preview-banner">
          Preview figures — not finalised. Run finalise to lock this period.
        </Alert>
      ) : null}

      {head?.figures_state === "no_preview" ? (
        <Alert color="yellow" data-testid="salary-sheet-no-preview">
          No preview has been run for this period. Open the pay period detail
          page and run Preview to populate the salary sheet.
        </Alert>
      ) : null}

      {head?.figures_state === "preview_out_of_scope" ? (
        <Alert color="yellow" data-testid="salary-sheet-preview-out-of-scope">
          {strings.payPeriods.previewOutOfScope}
        </Alert>
      ) : null}

      <Paper withBorder p="md">
        <Stack gap="sm">
          <Group justify="space-between" align="end">
            <TextInput
              label="Search"
              placeholder="Employee name or code"
              value={searchInput}
              onChange={(e) => setSearchInput(e.currentTarget.value)}
              style={{ maxWidth: 320 }}
              data-testid="salary-sheet-search"
            />
            <Group gap="sm">
              <Text size="sm" c="dimmed">
                {items.length} row{items.length === 1 ? "" : "s"} loaded
              </Text>
              <Button
                variant="default"
                onClick={onExportCsv}
                disabled={items.length === 0}
                data-testid="salary-sheet-export-csv"
              >
                Export CSV
              </Button>
            </Group>
          </Group>

          {sheetQuery.isPending ? (
            <Group justify="center" p="xl">
              <Loader data-testid="salary-sheet-loading" />
            </Group>
          ) : sheetQuery.isError ? (
            <Group justify="space-between" align="center">
              <Text c="red" size="sm" data-testid="salary-sheet-fetch-error">
                {sheetQuery.error instanceof PayPeriodsApiError
                  ? mapErrorCode(sheetQuery.error.code)
                  : strings.genericError}
              </Text>
              <Button
                size="xs"
                variant="default"
                onClick={() => sheetQuery.refetch()}
                data-testid="salary-sheet-retry"
              >
                {strings.common.retry}
              </Button>
            </Group>
          ) : items.length === 0 ? (
            <Text c="dimmed" data-testid="salary-sheet-empty">
              {q
                ? "No employees match your search."
                : "No payslips for this period yet."}
            </Text>
          ) : (
            <Table.ScrollContainer minWidth={1400}>
              <Table striped withTableBorder data-testid="salary-sheet-table">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Employee</Table.Th>
                    <Table.Th>Code</Table.Th>
                    <Table.Th>Basic</Table.Th>
                    <Table.Th>Additional</Table.Th>
                    <Table.Th>Gross</Table.Th>
                    <Table.Th>Pre-tax</Table.Th>
                    <Table.Th>Taxable</Table.Th>
                    <Table.Th>PAYE</Table.Th>
                    <Table.Th>UIF emp</Table.Th>
                    <Table.Th>UIF er</Table.Th>
                    <Table.Th>SDL</Table.Th>
                    <Table.Th>Other ded</Table.Th>
                    <Table.Th>Reimb</Table.Th>
                    <Table.Th>Net</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {items.map((r) => (
                    <Table.Tr
                      key={r.payslip_id}
                      data-testid={`salary-sheet-row-${r.employee_id}`}
                    >
                      <Table.Td>{r.employee_name}</Table.Td>
                      <Table.Td>{r.employee_code}</Table.Td>
                      <Table.Td>{r.basic_earnings}</Table.Td>
                      <Table.Td>{r.additional_earnings}</Table.Td>
                      <Table.Td data-testid={`salary-sheet-gross-${r.employee_id}`}>
                        {r.gross}
                      </Table.Td>
                      <Table.Td>{r.pre_tax_deductions}</Table.Td>
                      <Table.Td>{r.taxable_income}</Table.Td>
                      <Table.Td data-testid={`salary-sheet-paye-${r.employee_id}`}>
                        {r.paye}
                      </Table.Td>
                      <Table.Td>{r.uif_employee}</Table.Td>
                      <Table.Td>{r.uif_employer}</Table.Td>
                      <Table.Td>{r.sdl}</Table.Td>
                      <Table.Td>{r.other_deductions}</Table.Td>
                      <Table.Td>{r.reimbursements}</Table.Td>
                      <Table.Td data-testid={`salary-sheet-net-${r.employee_id}`}>
                        {r.net}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </Stack>
      </Paper>

      {sheetQuery.hasNextPage ? (
        <Group justify="center">
          <Button
            variant="default"
            onClick={() => sheetQuery.fetchNextPage()}
            loading={sheetQuery.isFetchingNextPage}
            data-testid="salary-sheet-load-more"
          >
            {strings.payPeriods.loadMore}
          </Button>
        </Group>
      ) : null}
    </Stack>
  );
}