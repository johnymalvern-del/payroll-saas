"""Job B frontend: PayslipSoFarPage + api function + route + strings."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

# ---- 1. api/payPeriods.ts: previewEmployeeAsOf ----
pp = SRC / "api" / "payPeriods.ts"
s = pp.read_text(encoding="utf-8")

if "export async function previewEmployeeAsOf" in s:
    print("payPeriods.ts: previewEmployeeAsOf already present")
else:
    # find where previewPayPeriodEmployee is defined (existing fn) to mirror style
    helper = '''export type PreviewEmployeeAsOfOut = {
  employee_id: string;
  employee_code: string;
  employee_name: string;
  pay_period_id: string;
  revision: number | null;
  status: string;
  as_of: string | null;
  available: boolean;
  reason_unavailable: string | null;
  gross: string | null;
  paye: string | null;
  net: string | null;
  warnings: string[];
  lines: {
    earning_type_code: string;
    earning_type_name: string;
    rate_source: string;
    amount: string;
    minutes: number | null;
  }[];
  deductions: {
    deduction_type_code: string;
    deduction_type_name: string;
    amount: string;
  }[];
  unacknowledged_formulas: string[];
  demo_values: boolean;
};

export async function previewEmployeeAsOf(
  periodId: string,
  employeeId: string,
  asOf: string,
): Promise<PreviewEmployeeAsOfOut> {
  const url = `/api/v1/payroll/pay-periods/${periodId}/preview/${employeeId}?as_of=${encodeURIComponent(asOf)}`;
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new PayPeriodsApiError(
      (err as { error?: { code?: string; message?: string } })?.error?.message ?? `HTTP ${res.status}`,
      (err as { error?: { code?: string } })?.error?.code ?? "http_error",
      res.status,
      (err as { error?: { details?: unknown } })?.error?.details ?? null,
    );
  }
  return (await res.json()) as PreviewEmployeeAsOfOut;
}

'''
    # append near the end but before any closing; simplest: append to file end
    s = s.rstrip() + "\n\n" + helper
    pp.write_text(s, encoding="utf-8")
    print("payPeriods.ts: previewEmployeeAsOf + type appended")

# ---- 2. PayslipSoFarPage.tsx ----
page = SRC / "pages" / "PayslipSoFarPage.tsx"
page.write_text('''import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import dayjs from "dayjs";
import { fetchPayPeriod, previewEmployeeAsOf } from "../api/payPeriods";
import { PageHeader } from "../components/layout/PageHeader";
import { colors } from "../theme/colors";

function todayISO(): string {
  return dayjs().format("YYYY-MM-DD");
}

function clampDate(d: string, start: string, end: string): string {
  if (d < start) return start;
  if (d > end) return end;
  return d;
}

export function PayslipSoFarPage() {
  const { id: periodId, employeeId } = useParams<{
    id: string;
    employeeId: string;
  }>();
  const [asOfRaw, setAsOf] = useState<string>(todayISO());

  const period = useQuery({
    queryKey: ["payPeriod", periodId],
    queryFn: () => fetchPayPeriod(periodId!),
    enabled: !!periodId,
    staleTime: 60_000,
  });

  const asOf = period.data
    ? clampDate(
        asOfRaw,
        period.data.start_date,
        period.data.end_date < todayISO()
          ? period.data.end_date
          : todayISO(),
      )
    : asOfRaw;

  const estimate = useQuery({
    queryKey: ["payslipSoFar", periodId, employeeId, asOf],
    queryFn: () => previewEmployeeAsOf(periodId!, employeeId!, asOf),
    enabled: !!periodId && !!employeeId && !!period.data,
    retry: false,
  });

  if (period.isLoading) {
    return (
      <Group justify="center" p="xl">
        <Loader />
      </Group>
    );
  }
  if (period.isError || !period.data) {
    return (
      <Alert color={colors.problem}>
        Could not load pay period.
      </Alert>
    );
  }

  const p = period.data;

  return (
    <Stack>
      <PageHeader
        title="Payslip so far"
        subtitle={`Period ${p.period_key} · ${p.start_date} → ${p.end_date}`}
      />

      <Alert
        color={colors.pending}
        data-testid="payslip-estimate-banner"
        title="ESTIMATE — period still open"
      >
        This is not a payslip. Finalise the period to issue a payslip.
      </Alert>

      {estimate.isError ? (
        <Alert color={colors.problem} data-testid="payslip-error">
          {(estimate.error as Error)?.message?.includes("403")
            ? "You do not have permission to view payroll previews."
            : "Could not load estimate."}
        </Alert>
      ) : null}

      {estimate.data?.demo_values ? (
        <Alert
          color={colors.info}
          data-testid="payslip-demo-banner"
        >
          Values below use demo/placeholder statutory tables. Real SARS
          tables are not loaded on this tenant.
        </Alert>
      ) : null}

      {estimate.data && estimate.data.unacknowledged_formulas.length > 0 ? (
        <Alert
          color={colors.pending}
          data-testid="payslip-formulas-banner"
        >
          {estimate.data.unacknowledged_formulas.length} payroll formula(s)
          not acknowledged. Values are best-effort.
        </Alert>
      ) : null}

      <Group align="flex-end" gap="lg">
        <TextInput
          label="As of"
          type="date"
          value={asOf}
          min={p.start_date}
          max={p.end_date < todayISO() ? p.end_date : todayISO()}
          onChange={(e) => setAsOf(e.currentTarget.value)}
          data-testid="payslip-asof-input"
          w={180}
        />
        <Stack gap={0}>
          <Text size="xs" c="dimmed">so far, up to</Text>
          <Text fw={700} data-testid="payslip-asof-label">
            {dayjs(asOf).format("D MMM YYYY")}
          </Text>
        </Stack>
      </Group>

      {estimate.isLoading || !estimate.data ? (
        <Group justify="center" p="xl">
          <Loader />
        </Group>
      ) : !estimate.data.available &&
        estimate.data.reason_unavailable === "monthly_proration_pending" ? (
        <Card data-testid="payslip-monthly-refusal">
          <Stack gap="xs">
            <Text fw={600}>
              Estimate not available for monthly salary
            </Text>
            <Text size="sm" c="dimmed">
              The proration rule for mid-month joiners and leavers has not
              been confirmed by the accountant yet. Until then, this figure
              would be misleading — no number is shown.
            </Text>
            <Text size="sm" c="dimmed">
              Employee: {estimate.data.employee_name} (
              {estimate.data.employee_code})
            </Text>
          </Stack>
        </Card>
      ) : !estimate.data.available ? (
        <Alert color={colors.pending} data-testid="payslip-unavailable">
          Estimate not available: {estimate.data.reason_unavailable ?? "unknown reason"}
        </Alert>
      ) : (
        <>
          <Card>
            <Stack gap="sm">
              <Text fw={600} size="lg">
                {estimate.data.employee_name} ({estimate.data.employee_code})
              </Text>
              <Text size="sm" c="dimmed">
                Hours by rate (aggregated by earning type)
              </Text>
              {estimate.data.lines.length === 0 ? (
                <Text size="sm" c="dimmed">
                  No earnings computed for days up to {asOf}.
                </Text>
              ) : (
                <Table data-testid="payslip-lines-table">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Earning</Table.Th>
                      <Table.Th>Minutes</Table.Th>
                      <Table.Th>Amount</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {estimate.data.lines.map((l, i) => (
                      <Table.Tr key={i}>
                        <Table.Td>{l.earning_type_name}</Table.Td>
                        <Table.Td>
                          {l.minutes === null ? "—" : l.minutes}
                        </Table.Td>
                        <Table.Td>{l.amount}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              )}
              <Text size="xs" c="dimmed">
                Rate multipliers per segment are visible in the attendance
                day panel for each work date.
              </Text>
            </Stack>
          </Card>

          <Group grow align="stretch">
            <Card data-testid="payslip-gross">
              <Text size="xs" c="dimmed">Gross</Text>
              <Text fw={700} size="xl">
                {estimate.data.gross ?? "—"}
              </Text>
            </Card>
            <Card data-testid="payslip-paye">
              <Text size="xs" c="dimmed">PAYE</Text>
              <Text fw={700} size="xl">
                {estimate.data.paye ?? "—"}
              </Text>
            </Card>
            <Card data-testid="payslip-net">
              <Text size="xs" c="dimmed">Net estimate</Text>
              <Text fw={700} size="xl">
                {estimate.data.net ?? "—"}
              </Text>
            </Card>
          </Group>

          <Card>
            <Stack gap="sm">
              <Text fw={600}>Deductions</Text>
              {estimate.data.deductions.length === 0 ? (
                <Text size="sm" c="dimmed">
                  No deductions computed.
                </Text>
              ) : (
                <Table data-testid="payslip-deductions-table">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Deduction</Table.Th>
                      <Table.Th>Amount</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {estimate.data.deductions.map((d, i) => (
                      <Table.Tr key={i}>
                        <Table.Td>{d.deduction_type_name}</Table.Td>
                        <Table.Td>{d.amount}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              )}
            </Stack>
          </Card>

          {estimate.data.warnings.length > 0 ? (
            <Alert color={colors.pending} data-testid="payslip-warnings">
              <Text fw={600}>Warnings</Text>
              <Stack gap={2}>
                {estimate.data.warnings.map((w, i) => (
                  <Text key={i} size="sm">
                    • {w}
                  </Text>
                ))}
              </Stack>
            </Alert>
          ) : null}
        </>
      )}
    </Stack>
  );
}
''', encoding="utf-8")
print("wrote PayslipSoFarPage.tsx")

# ---- 3. App.tsx route ----
app = SRC / "App.tsx"
s = app.read_text(encoding="utf-8")

if "PayslipSoFarPage" not in s:
    anchor = 'import { PayPeriodDetailPage } from "./pages/PayPeriodDetailPage";'
    if anchor in s:
        s = s.replace(
            anchor,
            anchor + '\nimport { PayslipSoFarPage } from "./pages/PayslipSoFarPage";',
            1,
        )
        print("App.tsx: PayslipSoFarPage import added")
    else:
        m = s.find('<Route path="payroll/pay-periods/:id"')
        if m > 0:
            s = s[:m] + 'import { PayslipSoFarPage } from "./pages/PayslipSoFarPage";\n' + s[m:]
            print("App.tsx: PayslipSoFarPage import added (fallback)")

if 'path="payroll/pay-periods/:id/payslip-so-far/:employeeId"' not in s:
    anchor = '<Route path="payroll/pay-periods/:id" element={<PayPeriodDetailPage />} />'
    if anchor in s:
        s = s.replace(
            anchor,
            anchor + '\n          <Route path="payroll/pay-periods/:id/payslip-so-far/:employeeId" element={<PayslipSoFarPage />} />',
            1,
        )
        print("App.tsx: payslip-so-far route added")
    else:
        raise SystemExit("FATAL: pay-periods/:id route anchor not found")

app.write_text(s, encoding="utf-8")