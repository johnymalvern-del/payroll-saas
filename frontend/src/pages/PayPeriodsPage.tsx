import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import {
  createPayPeriod,
  fetchPayPeriods,
  PayPeriodsApiError,
  type PayPeriodIn,
  type PayPeriodOut,
} from "../api/payPeriods";
import { mapErrorCode } from "../api/errors";
import { getSiteTz } from "../lib/config";
import { strings } from "../lib/strings";

dayjs.extend(utc);
dayjs.extend(timezone);

const PAGE_SIZE = 100;

const STATUS_OPTIONS = [
  { value: "all", label: strings.attendance.all },
  { value: "open", label: strings.payPeriods.statusOpen },
  { value: "locked", label: strings.payPeriods.statusLocked },
];

function statusColor(status: string): string {
  return status === "locked" ? "gray" : "green";
}

function localDate(d: string): string {
  return dayjs(d).format("DD MMM YYYY");
}

type FormState = {
  period_key: string;
  start_date: string;
  end_date: string;
  pay_date: string;
  cutoff_local: string;
};

const BLANK_FORM: FormState = {
  period_key: "",
  start_date: "",
  end_date: "",
  pay_date: "",
  cutoff_local: "",
};

function periodToIn(f: FormState): PayPeriodIn {
  return {
    period_key: f.period_key.trim(),
    start_date: f.start_date,
    end_date: f.end_date,
    pay_date: f.pay_date,
    cutoff_at: dayjs.tz(f.cutoff_local, getSiteTz()).toISOString(),
  };
}

export function PayPeriodsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<FormState>(BLANK_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  const periods = useInfiniteQuery({
    queryKey: ["pay_periods", statusFilter],
    queryFn: ({ pageParam }) =>
      fetchPayPeriods({
        status: statusFilter === "all" ? undefined : statusFilter,
        cursor: pageParam,
        limit: PAGE_SIZE,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const items: PayPeriodOut[] = useMemo(
    () => periods.data?.pages.flatMap((p) => p.items) ?? [],
    [periods.data],
  );

  const createMutation = useMutation({
    mutationFn: (payload: PayPeriodIn) => createPayPeriod(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pay_periods"] });
      setCreateOpen(false);
      setForm(BLANK_FORM);
      setFormError(null);
      setPageError(null);
    },
    onError: (err) => {
      if (err instanceof PayPeriodsApiError) {
        if (err.code === "period_key_taken") {
          setFormError(strings.payPeriods.errPeriodKeyTaken);
        } else if (err.code === "invalid_range") {
          setFormError(strings.payPeriods.errInvalidRange);
        } else if (err.code === "invalid_pay_date") {
          setFormError(strings.payPeriods.errInvalidPayDate);
        } else {
          setFormError(mapErrorCode(err.code));
        }
      } else {
        setFormError(strings.genericError);
      }
    },
  });

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((prev) => ({ ...prev, [k]: v }));

  const submitCreate = () => {
    setFormError(null);
    if (!form.period_key.trim()) {
      setFormError(strings.payPeriods.createErrKeyRequired);
      return;
    }
    if (!form.start_date || !form.end_date || !form.pay_date) {
      setFormError(strings.payPeriods.createErrDatesRequired);
      return;
    }
    if (dayjs(form.end_date).isBefore(dayjs(form.start_date), "day")) {
      setFormError(strings.payPeriods.createErrRange);
      return;
    }
    if (dayjs(form.pay_date).isBefore(dayjs(form.end_date), "day")) {
      setFormError(strings.payPeriods.createErrPayDate);
      return;
    }
    if (!form.cutoff_local) {
      setFormError(strings.payPeriods.createErrDatesRequired);
      return;
    }
    createMutation.mutate(periodToIn(form));
  };

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>{strings.payPeriods.title}</Title>
        <Button
          onClick={() => {
            setForm(BLANK_FORM);
            setFormError(null);
            setCreateOpen(true);
          }}
          data-testid="pay-periods-new"
        >
          {strings.payPeriods.newButton}
        </Button>
      </Group>

      {pageError ? (
        <Alert
          color="red"
          withCloseButton
          onClose={() => setPageError(null)}
          data-testid="pay-periods-error"
        >
          {pageError}
        </Alert>
      ) : null}

      <Paper withBorder p="md">
        <SegmentedControl
          value={statusFilter}
          onChange={setStatusFilter}
          data={STATUS_OPTIONS}
          data-testid="pay-periods-status-filter"
        />
      </Paper>

      <Paper withBorder p="md">
        {periods.isPending ? (
          <Group justify="center" p="xl">
            <Loader />
          </Group>
        ) : periods.isError ? (
          <Group justify="space-between" align="center">
            <Text c="red" size="sm" data-testid="pay-periods-load-error">
              {strings.payPeriods.error}
            </Text>
            <Button
              size="xs"
              variant="default"
              onClick={() => periods.refetch()}
              data-testid="pay-periods-retry"
            >
              {strings.common.retry}
            </Button>
          </Group>
        ) : items.length === 0 ? (
          <Text c="dimmed">{strings.payPeriods.empty}</Text>
        ) : (
          <Stack gap="sm" data-testid="pay-periods-list">
            {items.map((p) => (
              <Paper
                key={p.id}
                withBorder
                p="sm"
                data-testid={`pay-period-${p.id}`}
              >
                <Group justify="space-between" align="center" wrap="nowrap">
                  <Stack gap={2}>
                    <Group gap="sm">
                      <Text fw={600}>{p.period_key}</Text>
                      <Badge color={statusColor(p.status)} variant="light">
                        {p.status}
                      </Badge>
                    </Group>
                    <Text size="xs" c="dimmed">
                      {localDate(p.start_date)} → {localDate(p.end_date)}
                      {" · "}
                      {strings.payPeriods.rowPayDate}: {localDate(p.pay_date)}
                    </Text>
                  </Stack>
                <Button
                  size="xs"
                  variant="default"
                  onClick={() => navigate(`/payroll/pay-periods/${p.id}`)}
                  data-testid={`pay-period-open-${p.id}`}
                >
                  {strings.payPeriods.openDetail}
                </Button>
                </Group>
              </Paper>
            ))}
          </Stack>
        )}
      </Paper>

      {periods.hasNextPage ? (
        <Group justify="center">
          <Button
            variant="default"
            onClick={() => periods.fetchNextPage()}
            loading={periods.isFetchingNextPage}
            data-testid="pay-periods-load-more"
          >
            {strings.payPeriods.loadMore}
          </Button>
        </Group>
      ) : null}

      <Modal
        opened={createOpen}
        onClose={() => {
          if (createMutation.isPending) return;
          setCreateOpen(false);
        }}
        title={strings.payPeriods.createTitle}
        data-testid="pay-periods-create-modal"
      >
        <Stack gap="sm">
          {formError ? (
            <Alert color="red" data-testid="pay-periods-create-error">
              {formError}
            </Alert>
          ) : null}
          <TextInput
            label={strings.payPeriods.createPeriodKey}
            value={form.period_key}
            onChange={(e) => set("period_key", e.currentTarget.value)}
            placeholder="2026-11"
            required
            data-testid="pay-periods-create-key"
          />
          <Group grow>
            <TextInput
              label={strings.payPeriods.createStart}
              type="date"
              value={form.start_date}
              onChange={(e) => set("start_date", e.currentTarget.value)}
              required
              data-testid="pay-periods-create-start"
            />
            <TextInput
              label={strings.payPeriods.createEnd}
              type="date"
              value={form.end_date}
              onChange={(e) => set("end_date", e.currentTarget.value)}
              required
              data-testid="pay-periods-create-end"
            />
          </Group>
          <Group grow>
            <TextInput
              label={strings.payPeriods.createPayDate}
              type="date"
              value={form.pay_date}
              onChange={(e) => set("pay_date", e.currentTarget.value)}
              required
              data-testid="pay-periods-create-pay-date"
            />
            <TextInput
              label={strings.payPeriods.createCutoff}
              type="datetime-local"
              value={form.cutoff_local}
              onChange={(e) => set("cutoff_local", e.currentTarget.value)}
              required
              data-testid="pay-periods-create-cutoff"
            />
          </Group>
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => setCreateOpen(false)}
              disabled={createMutation.isPending}
              data-testid="pay-periods-create-cancel"
            >
              {strings.payPeriods.createCancel}
            </Button>
            <Button
              onClick={submitCreate}
              loading={createMutation.isPending}
              data-testid="pay-periods-create-submit"
            >
              {strings.payPeriods.createSubmit}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
