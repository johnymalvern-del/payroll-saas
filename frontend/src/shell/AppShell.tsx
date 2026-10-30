import { Link as RouterLink, Outlet, useLocation } from "react-router-dom";
import {
  Anchor,
  AppShell as MantineAppShell,
  Button,
  Group,
  Menu,
  Text,
} from "@mantine/core";
import { useAuth } from "../auth/AuthContext";
import { useMe } from "../auth/useMe";
import { buildNav } from "./nav";
import { strings } from "../lib/strings";

export function AppShell() {
  const { logout } = useAuth();
  const me = useMe();
  const location = useLocation();
  const nav = buildNav(me.data?.permissions ?? []);

  return (
    <MantineAppShell header={{ height: 56 }} padding="md">
      <MantineAppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="md" wrap="nowrap">
            <Anchor component={RouterLink} to="/" underline="never">
              <Text fw={700}>{strings.appName}</Text>
            </Anchor>
            <Group gap="sm" wrap="wrap">
              {nav.map((item) => {
                const active = location.pathname.startsWith(item.to);
                return (
                  <Anchor
                    key={item.to}
                    component={RouterLink}
                    to={item.to}
                    underline="never"
                    fw={active ? 600 : 400}
                  >
                    {item.label}
                  </Anchor>
                );
              })}
            </Group>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <Button variant="light" size="xs">
                  {me.data?.username ?? "…"}
                </Button>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{strings.shell.roleLabel(me.data?.role ?? "")}</Menu.Label>
                <Menu.Item onClick={() => void logout()}>
                  {strings.shell.logout}
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </MantineAppShell.Header>
      <MantineAppShell.Main>
        <Outlet />
      </MantineAppShell.Main>
    </MantineAppShell>
  );
}
