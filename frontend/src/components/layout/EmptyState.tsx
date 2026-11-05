import { Paper, Stack, Text } from "@mantine/core";

export function EmptyState({ message }: { message: string }) {
  return (
    <Paper p="xl" withBorder style={{ textAlign: "center" }}>
      <Stack gap="xs" align="center">
        <Text c="dimmed" size="sm">
          {message}
        </Text>
      </Stack>
    </Paper>
  );
}
