import { Link as RouterLink, Outlet, useLocation } from "react-router-dom";
import {
  AppShell as MantineAppShell,
  Burger,
  Button,
  Group,
  Menu,
  ScrollArea,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useAuth } from "../auth/AuthContext";
import { useMe } from "../auth/useMe";
import { buildNav } from "./nav";
import { strings } from "../lib/strings";
import { Icon } from "../components/layout/Icon";

export function AppShell() {
  const { logout } = useAuth();
  const me = useMe();
  const location = useLocation();
  const [opened, { toggle, close }] = useDisclosure();
  const nav = buildNav(me.data?.permissions ?? []);

  return (
    <MantineAppShell
      header={{ height: 56 }}
      navbar={{ width: 248, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <MantineAppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
              aria-label="Toggle navigation"
            />
            <Text fw={700} size="md">
              {strings.appName}
            </Text>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <Button variant="subtle" size="xs">
                  {me.data?.username ?? "\u2026"}
                </Button>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>
                  {strings.shell.roleLabel(me.data?.role ?? "")}
                </Menu.Label>
                <Menu.Item onClick={() => void logout()}>
                  {strings.shell.logout}
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </MantineAppShell.Header>

      <MantineAppShell.Navbar p="sm">
        <ScrollArea>
          <Stack gap={4}>
            {nav.map((group) => (
              <Stack key={group.label ?? "_home"} gap={2} mt="sm">
                {group.label ? (
                  <Text
                    size="xs"
                    c="dimmed"
                    fw={600}
                    tt="uppercase"
                    pl="sm"
                    pb={4}
                  >
                    {group.label}
                  </Text>
                ) : null}
                {group.items.map((item) => {
                  const active =
                    item.to === "/"
                      ? location.pathname === "/"
                      : location.pathname.startsWith(item.to);
                  return (
                    <UnstyledButton
                      key={item.to}
                      component={RouterLink}
                      to={item.to}
                      onClick={close}
                      style={{
                        display: "block",
                        padding: "8px 12px",
                        borderRadius: 8,
                        backgroundColor: active
                          ? "var(--mantine-color-navy-0)"
                          : "transparent",
                        color: active
                          ? "var(--mantine-color-navy-7)"
                          : "var(--mantine-color-text)",
                        fontWeight: active ? 600 : 400,
                      }}
                    >
                      <Group gap="sm" wrap="nowrap">
                        <Icon name={item.icon} size={18} />
                        <Text size="sm">{item.label}</Text>
                      </Group>
                    </UnstyledButton>
                  );
                })}
              </Stack>
            ))}
          </Stack>
        </ScrollArea>
      </MantineAppShell.Navbar>

      <MantineAppShell.Main>
        <Outlet />
      </MantineAppShell.Main>
    </MantineAppShell>
  );
}
