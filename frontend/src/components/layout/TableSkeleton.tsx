import { Skeleton, Table } from "@mantine/core";

export function TableSkeleton({ rows = 6, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          {Array.from({ length: cols }, (_, i) => (
            <Table.Th key={i}>
              <Skeleton height={10} width={80} />
            </Table.Th>
          ))}
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {Array.from({ length: rows }, (_, r) => (
          <Table.Tr key={r}>
            {Array.from({ length: cols }, (_, c) => (
              <Table.Td key={c}>
                <Skeleton height={14} />
              </Table.Td>
            ))}
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
