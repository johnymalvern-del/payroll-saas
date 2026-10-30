import { Card, Stack, Text, Title } from "@mantine/core";

export function PlaceholderPage({
  title,
  phase,
}: {
  title: string;
  phase: string;
}) {
  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Title order={3}>{title}</Title>
        <Text c="dimmed">{phase}</Text>
      </Stack>
    </Card>
  );
}
