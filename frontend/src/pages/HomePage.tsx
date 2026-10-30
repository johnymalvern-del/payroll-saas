import { Link as RouterLink } from "react-router-dom";
import { Anchor, Card, Group, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useMe } from "../auth/useMe";
import { strings } from "../lib/strings";

type HomeCard = { title: string; body: string; cta: string; to: string };

function cardsFor(permissions: string[]): HomeCard[] {
  const set = new Set(permissions);
  const out: HomeCard[] = [];
  if (set.has("attendance_view")) {
    out.push({
      title: strings.home.cards.attendance.title,
      body: strings.home.cards.attendance.body,
      cta: strings.home.cards.attendance.cta,
      to: "/attendance",
    });
  }
  if (set.has("exception_resolve")) {
    out.push({
      title: strings.home.cards.exceptions.title,
      body: strings.home.cards.exceptions.body,
      cta: strings.home.cards.exceptions.cta,
      to: "/attendance/exceptions",
    });
  }
  if (set.has("employee_crud")) {
    out.push({
      title: strings.home.cards.employees.title,
      body: strings.home.cards.employees.body,
      cta: strings.home.cards.employees.cta,
      to: "/employees",
    });
  }
  if (set.has("payroll_preview")) {
    out.push({
      title: strings.home.cards.payPeriods.title,
      body: strings.home.cards.payPeriods.body,
      cta: strings.home.cards.payPeriods.cta,
      to: "/payroll/pay-periods",
    });
  }
  if (set.has("pay_rate_view")) {
    out.push({
      title: strings.home.cards.changeRequests.title,
      body: strings.home.cards.changeRequests.body,
      cta: strings.home.cards.changeRequests.cta,
      to: "/payroll/change-requests",
    });
  }
  if (set.has("audit_view")) {
    out.push({
      title: strings.home.cards.auditLog.title,
      body: strings.home.cards.auditLog.body,
      cta: strings.home.cards.auditLog.cta,
      to: "/audit-log",
    });
  }
  if (set.has("org_manage")) {
    out.push({
      title: strings.home.cards.setup.title,
      body: strings.home.cards.setup.body,
      cta: strings.home.cards.setup.cta,
      to: "/setup",
    });
  }
  if (out.length === 0) {
    out.push({
      title: strings.home.cards.payslips.title,
      body: strings.home.cards.payslips.body,
      cta: strings.home.cards.payslips.cta,
      to: "/payslips",
    });
  }
  return out;
}

export function HomePage() {
  const me = useMe();
  const cards = cardsFor(me.data?.permissions ?? []);

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Title order={2}>{strings.home.welcome(me.data?.username ?? "")}</Title>
        <Text c="dimmed" size="sm">
          {strings.home.roleLabel(me.data?.role ?? "")}
        </Text>
      </Stack>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
        {cards.map((card) => (
          <Card key={card.to} withBorder padding="md">
            <Stack gap="sm">
              <Title order={4}>{card.title}</Title>
              <Text size="sm">{card.body}</Text>
              <Group justify="flex-end">
                <Anchor component={RouterLink} to={card.to} size="sm">
                  {card.cta}
                </Anchor>
              </Group>
            </Stack>
          </Card>
        ))}
      </SimpleGrid>
    </Stack>
  );
}
