import { Link as RouterLink, Outlet, useLocation } from "react-router-dom";
import {
  Anchor,
  AppShell as MantineAppShell,
  Box,
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
import { tokens } from "../theme";

export function AppShell() {
  const { logout } = useAuth();
  const me = useMe();
  const location = useLocation();
  const [opened, { toggle, close }] = useDisclosure();
  const nav = buildNav(me.data?.permissions ?? []);

  return (
    <MantineAppShell
      header={{ height: 56 }}
      navbar={{ width: 240, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <MantineAppShell.Header
        style={{
          backgroundColor: tokens.cardBg,
          borderBottom: `1px solid ${tokens.hairline}`,
        }}
      >
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="md" wrap="nowrap">
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
              aria-label="Toggle navigation"
            />
            <Anchor
              component={RouterLink}
              to="/"
              underline="never"
              style={{ color: "inherit" }}
            >
              <Group gap="xs" wrap="nowrap">
                <Box
                  style={{
                    width: 30,
                    height: 30,
                    borderRadius: 8,
                    backgroundColor: tokens.tile.mint.bg,
                    color: tokens.tile.mint.text,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 600,
                    fontSize: 14,
                  }}
                >
                  {strings.appName.charAt(0)}
                </Box>
                <Text fw={600} size="md" style={{ color: tokens.text }}>
                  {strings.appName}
                </Text>
              </Group>
            </Anchor>
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

      <MantineAppShell.Navbar
        p="md"
        style={{
          backgroundColor: tokens.menuBg,
          borderRight: "none",
        }}
      >
        <ScrollArea>
          <Stack gap="md">
            {nav.map((group) => (
              <Stack key={group.label ?? "_home"} gap={4}>
                {group.label ? (
                  <Text
                    size="xs"
                    fw={500}
                    tt="uppercase"
                    px="md"
                    py={4}
                    style={{
                      color: tokens.menuMutedText,
                      letterSpacing: 0.5,
                    }}
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
                        padding: "10px 14px",
                        borderRadius: 999,
                        backgroundColor: active
                          ? tokens.menuActiveBg
                          : "transparent",
                        color: active
                          ? tokens.menuActiveText
                          : tokens.menuText,
                        fontWeight: active ? 600 : 400,
                        fontSize: 14,
                        transition: "background-color 120ms ease",
                      }}
                    >
                      {item.label}
                    </UnstyledButton>
                  );
                })}
              </Stack>
            ))}
          </Stack>
        </ScrollArea>
      </MantineAppShell.Navbar>

      <MantineAppShell.Main style={{ backgroundColor: tokens.pageBg }}>
        <Outlet />
      </MantineAppShell.Main>
    </MantineAppShell>
  );
}
