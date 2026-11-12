import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Table,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import {
  fetchPayPeriod,
  fetchReopenLog,
  finalisePayPeriod,
  PayPeriodsApiError,
  previewPayPeriod,
  reopenPayPeriod,
  type PreviewOut,
} from "../api/payPeriods";
import { mapErrorCode } from "../api/errors";
import { strings } from "../lib/strings";
import { colors } from "../theme/colors";

dayjs.extend(utc);
dayjs.extend(timezone);

function localDate(d: string): string {
  return dayjs(d).format("DD MMM YYYY");
}

function localDateTime(d: string): string {
  return dayjs(d).format("DD MMM YYYY HH:mm");
}

function statusColor(status: string): string {
  return status === "locked" ? "gray" : "green";
}

export function PayPeriodDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [previewData, setPreviewData] = useState<PreviewOut | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const [finaliseOpen, setFinaliseOpen] = useState(false);
  const [finaliseAck, setFinaliseAck] = useState("");
  const [finaliseError, setFinaliseError] = useState<string | null>(null);
  const [needsAck, setNeedsAck] = useState(false);
  const [needsStaleAck, setNeedsStaleAck] = useState(false);
  const [staleAckReason, setStaleAckReason] = useState("");
  const [pendingCrCount, setPendingCrCount] = useState<number | null>(null);

  const [reopenOpen, setReopenOpen] = useState(false);
  const [reopenReason, setReopenReason] = useState("");
  const [reopenError, setReopenError] = useState<string | null>(null);

  const periodQuery = useQuery({
    queryKey: ["pay_period", id],
    queryFn: () => fetchPayPeriod(id!),
    enabled: !!id,
  });

  const period = periodQuery.data ?? null;

  const reopenLogQuery = useQuery({
    queryKey: ["pay_period_reopen_log", id],
    queryFn: () => fetchReopenLog(id!),
    enabled: !!id && period?.status === "locked",
  });

  const previewMutation = useMutation({
    mutationFn: () => previewPayPeriod({ id: id! }),
    onSuccess: (data) => {
      setPreviewData(data);
      setPreviewError(null);
    },
    onError: (err) => {
      setPreviewData(null);
      setPreviewError(
        err instanceof PayPeriodsApiError
          ? mapErrorCode(err.code)
          : strings.genericError,
      );
    },
  });

  const resetFinaliseState = () => {
    setFinaliseAck("");
    setFinaliseError(null);
    setNeedsAck(false);
    setNeedsStaleAck(false);
    setStaleAckReason("");
    setPendingCrCount(null);
  };

  const finaliseMutation = useMutation({
    mutationFn: ({
      ack,
      staleAck,
    }: {
      ack: string | null;
      staleAck: string | null;
    }) => finalisePayPeriod(id!, ack, staleAck),
    onSuccess: () => {
      setFinaliseOpen(false);
      resetFinaliseState();
      qc.invalidateQueries({ queryKey: ["pay_period", id] });
      qc.invalidateQueries({ queryKey: ["pay_periods"] });
      qc.invalidateQueries({ queryKey: ["pay_period_reopen_log", id] });
    },
    onError: (err) => {
      if (err instanceof PayPeriodsApiError) {
        if (err.code === "open_exceptions_in_period") {
          setNeedsAck(true);
          setFinaliseError(strings.payPeriods.errOpenExceptions);
        } else if (err.code === "pending_change_requests_in_period") {
          const rawCount = err.details?.count;
          const count =
            typeof rawCount === "number" && Number.isFinite(rawCount)
              ? rawCount
              : 0;
          setPendingCrCount(count);
          setFinaliseError(strings.payPeriods.errPendingChangeRequests(count));
        } else if (err.code === "preview_stale") {
          setNeedsStaleAck(true);
          setFinaliseError(strings.payPeriods.errPreviewStale);
        } else if (err.code === "period_locked") {
          setFinaliseError(strings.payPeriods.errPeriodLocked);
        } else {
          setFinaliseError(mapErrorCode(err.code));
        }
      } else {
        setFinaliseError(strings.genericError);
      }
    },
  });

  const reopenMutation = useMutation({
    mutationFn: (reason: string) => reopenPayPeriod(id!, reason),
    onSuccess: () => {
      setReopenOpen(false);
      setReopenReason("");
      setReopenError(null);
      qc.invalidateQueries({ queryKey: ["pay_period", id] });
      qc.invalidateQueries({ queryKey: ["pay_periods"] });
      qc.invalidateQueries({ queryKey: ["pay_period_reopen_log", id] });
    },
    onError: (err) => {
      setReopenError(
        err instanceof PayPeriodsApiError
          ? mapErrorCode(err.code)
          : strings.genericError,
      );
    },
  });

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

  if (periodQuery.isError || !period) {
    return (
      <Alert color={colors.problem} data-testid="pay-period-detail-error">
        {strings.payPeriods.detailLoadError}
      </Alert>
    );
  }

  const isLocked = period.status === "locked";

  const onPreview = () => {
    setPreviewError(null);
    previewMutation.mutate();
  };

  const onSubmitFinalise = () => {
    const ack = finaliseAck.trim() ? finaliseAck.trim() : null;
    if (needsAck && !ack) {
      setFinaliseError(strings.payPeriods.finaliseAckRequired);
      return;
    }
    const staleAck = staleAckReason.trim() ? staleAckReason.trim() : null;
    if (needsStaleAck && !staleAck) {
      setFinaliseError(strings.payPeriods.previewStaleAckRequired);
      return;
    }
    finaliseMutation.mutate({ ack, staleAck });
  };

  const onSubmitReopen = () => {
    if (!reopenReason.trim()) {
      setReopenError(strings.payPeriods.reopenReasonRequired);
      return;
    }
    reopenMutation.mutate(reopenReason.trim());
  };

  const onRerunPreview = () => {
    setFinaliseOpen(false);
    resetFinaliseState();
    previewMutation.mutate();
  };

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Group gap="sm">
          <Button
            variant="default"
            onClick={() => navigate("/payroll/pay-periods")}
            data-testid="pay-period-detail-back"
          >
            ←
          </Button>
          <Title order={2}>
            {strings.payPeriods.detailTitle(period.period_key)}
          </Title>
          <Badge color={statusColor(period.status)} variant="light">
            {period.status}
          </Badge>
        </Group>
        <Group gap="sm">
          <Button
            variant="default"
            onClick={onPreview}
            loading={previewMutation.isPending}
            disabled={isLocked}
            data-testid="pay-period-preview"
          >
            {strings.payPeriods.previewButton}
          </Button>
          <Button
            variant="default"
            onClick={() => navigate(`/payroll/pay-periods/${id}/salary-sheet`)}
            data-testid="pay-period-salary-sheet-open"
          >
            Salary sheet
          </Button>
          <Button
            onClick={() => {
              resetFinaliseState();
              setFinaliseOpen(true);
            }}
            disabled={isLocked}
            data-testid="pay-period-finalise-open"
          >
            {strings.payPeriods.finaliseButton}
          </Button>
          <Button
            variant="default"
            onClick={() => {
              setReopenReason("");
              setReopenError(null);
              setReopenOpen(true);
            }}
            disabled={!isLocked}
            data-testid="pay-period-reopen-open"
          >
            {strings.payPeriods.reopenButton}
          </Button>
        </Group>
      </Group>

      <Paper withBorder p="md">
        <Stack gap="xs">
          <Group gap="lg">
            <Text size="sm">
              {localDate(period.start_date)} → {localDate(period.end_date)}
            </Text>
            <Text size="sm">
              {strings.payPeriods.rowPayDate}: {localDate(period.pay_date)}
            </Text>
            <Text size="sm">
              Cutoff: {localDateTime(period.cutoff_at)}
            </Text>
          </Group>
        </Stack>
      </Paper>

      {previewError ? (
        <Alert color={colors.problem} data-testid="pay-period-preview-error">
          {previewError}
        </Alert>
      ) : null}

      {previewData ? (
        <Paper withBorder p="md" data-testid="pay-period-preview-result">
          <Stack gap="sm">
            <Text fw={600}>{strings.payPeriods.previewTitle}</Text>
            {previewData.unacknowledged_formulas.length > 0 ? (
              <Alert color={colors.warning}>
                Unacknowledged formulas:{" "}
                {previewData.unacknowledged_formulas.join(", ")}
              </Alert>
            ) : null}
            {previewData.items.length === 0 ? (
              previewData.raw_employee_count > 0 ? (
                <Alert
                  color={colors.warning}
                  data-testid="pay-period-preview-out-of-scope"
                >
                  {strings.payPeriods.previewOutOfScope}
                </Alert>
              ) : (
                <Text c="dimmed">{strings.payPeriods.previewEmpty}</Text>
              )
            ) : (
              <Table.ScrollContainer minWidth={600}>
                <Table striped withTableBorder>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Employee</Table.Th>
                      <Table.Th>{strings.payPeriods.previewGross}</Table.Th>
                      <Table.Th>{strings.payPeriods.previewPaye}</Table.Th>
                      <Table.Th>{strings.payPeriods.previewNet}</Table.Th>
                      <Table.Th>
                        {strings.payPeriods.previewWarningsHeader}
                      </Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {previewData.items.map((row) => (
                      <Table.Tr
                        key={row.employee_id}
                        data-testid={`preview-row-${row.employee_id}`}
                      >
                        <Table.Td>
                          {row.employee_name}
                          {row.employee_code
                            ? ` (${row.employee_code})`
                            : ""}
                        </Table.Td>
                        <Table.Td>{row.gross}</Table.Td>
                        <Table.Td>{row.paye}</Table.Td>
                        <Table.Td>{row.net}</Table.Td>
                        <Table.Td>
                          {row.warnings.length > 0
                            ? row.warnings.join(" · ")
                            : "—"}
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            )}
          </Stack>
        </Paper>
      ) : null}

      {isLocked && reopenLogQuery.data && reopenLogQuery.data.length > 0 ? (
        <Paper withBorder p="md" data-testid="pay-period-reopen-log">
          <Stack gap="xs">
            <Text fw={600}>{strings.payPeriods.reopenLogTitle}</Text>
            {reopenLogQuery.data.map((r) => (
              <Text key={r.id} size="sm">
                {localDateTime(r.occurred_at)} ·{" "}
                {strings.payPeriods.reopenLogPrior}: {r.prior_revision} →{" "}
                {strings.payPeriods.reopenLogNew}: {r.new_revision} · {r.reason}
              </Text>
            ))}
          </Stack>
        </Paper>
      ) : null}

      <Modal
        opened={finaliseOpen}
        onClose={() => {
          if (finaliseMutation.isPending) return;
          setFinaliseOpen(false);
          resetFinaliseState();
        }}
        title={strings.payPeriods.finaliseTitle}
        data-testid="pay-period-finalise-modal"
      >
        <Stack gap="sm">
          <Text size="sm">{strings.payPeriods.finaliseBody}</Text>

          {finaliseError ? (
            <Alert color={colors.problem} data-testid="pay-period-finalise-error">
              {finaliseError}
            </Alert>
          ) : null}

          {pendingCrCount !== null ? (
            <Alert
              color={colors.warning}
              data-testid="pay-period-finalise-pending-cr-guidance"
            >
              {strings.payPeriods.pendingChangeRequestsGuidance}
            </Alert>
          ) : null}

          {needsStaleAck ? (
            <Alert
              color={colors.warning}
              data-testid="pay-period-finalise-stale-warning"
            >
              {strings.payPeriods.previewStaleWarningBody}
            </Alert>
          ) : null}

          <Textarea
            label={strings.payPeriods.finaliseAckLabel}
            description={strings.payPeriods.finaliseAckHint}
            value={finaliseAck}
            onChange={(e) => setFinaliseAck(e.currentTarget.value)}
            minRows={2}
            data-testid="pay-period-finalise-ack"
          />

          {needsStaleAck ? (
            <Textarea
              label={strings.payPeriods.previewStaleAckLabel}
              description={strings.payPeriods.previewStaleAckHint}
              value={staleAckReason}
              onChange={(e) => setStaleAckReason(e.currentTarget.value)}
              minRows={2}
              data-testid="pay-period-finalise-stale-ack"
            />
          ) : null}

          <Group justify="flex-end">
            {needsStaleAck ? (
              <Button
                variant="default"
                onClick={onRerunPreview}
                disabled={finaliseMutation.isPending}
                data-testid="pay-period-finalise-rerun-preview"
              >
                {strings.payPeriods.rerunPreviewButton}
              </Button>
            ) : null}
            <Button
              variant="default"
              onClick={() => {
                setFinaliseOpen(false);
                resetFinaliseState();
              }}
              disabled={finaliseMutation.isPending}
              data-testid="pay-period-finalise-cancel"
            >
              {strings.common.cancel}
            </Button>
            <Button
              onClick={onSubmitFinalise}
              loading={finaliseMutation.isPending}
              disabled={pendingCrCount !== null}
              data-testid="pay-period-finalise-submit"
            >
              {strings.payPeriods.finaliseConfirm}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={reopenOpen}
        onClose={() => {
          if (reopenMutation.isPending) return;
          setReopenOpen(false);
          setReopenReason("");
          setReopenError(null);
        }}
        title={strings.payPeriods.reopenTitle}
        data-testid="pay-period-reopen-modal"
      >
        <Stack gap="sm">
          <Text size="sm">{strings.payPeriods.reopenBody}</Text>
          {reopenError ? (
            <Alert color={colors.problem} data-testid="pay-period-reopen-error">
              {reopenError}
            </Alert>
          ) : null}
          <Textarea
            label={strings.payPeriods.reopenReasonLabel}
            value={reopenReason}
            onChange={(e) => setReopenReason(e.currentTarget.value)}
            minRows={2}
            required
            data-testid="pay-period-reopen-reason"
          />
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => {
                setReopenOpen(false);
                setReopenReason("");
                setReopenError(null);
              }}
              disabled={reopenMutation.isPending}
              data-testid="pay-period-reopen-cancel"
            >
              {strings.common.cancel}
            </Button>
            <Button
              onClick={onSubmitReopen}
              loading={reopenMutation.isPending}
              data-testid="pay-period-reopen-submit"
            >
              {strings.payPeriods.reopenConfirm}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}