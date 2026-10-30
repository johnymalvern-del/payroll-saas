import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Group,
  Modal,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { markReviewed, type MarkReviewedOut } from "../../api/attendance";
import { strings } from "../../lib/strings";

type Props = {
  opened: boolean;
  fromDate: string;
  toDate: string;
  siteId: string | null;
  branchId: string | null;
  departmentId: string | null;
  includeTerminated: boolean;
  onClose: () => void;
};

export function MarkReviewedModal({
  opened,
  fromDate,
  toDate,
  siteId,
  branchId,
  departmentId,
  includeTerminated,
  onClose,
}: Props) {
  const [result, setResult] = useState<MarkReviewedOut | null>(null);
  const mutation = useMutation({
    mutationFn: () =>
      markReviewed({
        fromDate,
        toDate,
        siteId,
        branchId,
        departmentId,
        includeTerminated,
      }),
    onSuccess: (data) => setResult(data),
  });

  const close = () => {
    setResult(null);
    mutation.reset();
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={close}
      title={strings.attendance.markReviewed.title}
      size="lg"
    >
      <Stack gap="md">
        <Text size="sm">{strings.attendance.markReviewed.body}</Text>
        {mutation.isError ? (
          <Alert color="red">{strings.attendance.markReviewed.error}</Alert>
        ) : null}
        {result ? (
          <Alert color={result.refused_days.length === 0 ? "green" : "orange"}>
            {result.reviewed_count} {strings.attendance.markReviewed.reviewedCount}
            {result.refused_days.length > 0
              ? ` · ${result.refused_days.length} ${strings.attendance.markReviewed.refusedCount}`
              : ""}
          </Alert>
        ) : null}
        {result && result.refused_days.length > 0 ? (
          <Table striped withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{strings.attendance.markReviewed.employee}</Table.Th>
                <Table.Th>{strings.attendance.markReviewed.date}</Table.Th>
                <Table.Th>{strings.attendance.markReviewed.reason}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {result.refused_days.map((r) => (
                <Table.Tr key={`${r.employee_id}-${r.work_date}`}>
                  <Table.Td>{r.employee_name ?? r.employee_id}</Table.Td>
                  <Table.Td>{r.work_date}</Table.Td>
                  <Table.Td>
                    <Badge color="orange" variant="light">
                      {r.reason}
                    </Badge>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : null}
        <Group justify="space-between">
          <Button variant="default" onClick={close}>
            {strings.attendance.markReviewed.close}
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
            disabled={!!result && result.refused_days.length === 0}
          >
            {result ? strings.attendance.markReviewed.again : strings.attendance.markReviewed.submit}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
