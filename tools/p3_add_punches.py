"""Restore the punches table in DayPanel.tsx between rate breakdown and
exceptions. Required by AttendanceSheetPage.test.tsx:198."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P = ROOT / "frontend" / "src" / "components" / "AttendanceSheet" / "DayPanel.tsx"
s = P.read_text(encoding="utf-8")

anchor = '''          <Stack gap={4}>
            <Text size="sm" fw={500}>{strings.attendance.dayPanel.exceptions}</Text>'''
if "Punches</Text>" in s or "dayPanel.punches" in s:
    print("punches section already present")
else:
    if anchor not in s:
        raise SystemExit("FATAL: exceptions block anchor not found")
    punches = '''          <Stack gap={4}>
            <Text size="sm" fw={500}>{strings.attendance.dayPanel.punches}</Text>
            {day.data.punches.length === 0 ? (
              <Text size="sm" c="dimmed">
                {strings.attendance.dayPanel.noPunches}
              </Text>
            ) : (
              <Table striped withTableBorder>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Time</Table.Th>
                    <Table.Th>Direction</Table.Th>
                    <Table.Th>Source</Table.Th>
                    <Table.Th>Confidence</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {day.data.punches.map((p) => (
                    <Table.Tr key={p.id}>
                      <Table.Td>{dayjs(p.punch_time).format("HH:mm:ss")}</Table.Td>
                      <Table.Td>{p.direction}</Table.Td>
                      <Table.Td>{p.source}</Table.Td>
                      <Table.Td>
                        {p.confidence === null ? "\\u2014" : p.confidence}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
          </Stack>

''' + anchor
    s = s.replace(anchor, punches, 1)
    P.write_text(s, encoding="utf-8")
    print("punches section inserted before exceptions")