import { Container, Stack, Text, Title } from "@mantine/core";
import { strings } from "./lib/strings";

export default function App() {
  return (
    <Container size="sm" py="xl">
      <Stack>
        <Title order={1}>{strings.appName}</Title>
        <Text c="dimmed">{strings.scaffold.ready}</Text>
        <Text size="sm">{strings.scaffold.next}</Text>
      </Stack>
    </Container>
  );
}
