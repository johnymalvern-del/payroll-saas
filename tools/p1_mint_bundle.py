"""Bundle: fix date-picker test + P1 Mint theme.

Files touched:
- frontend/src/pages/PayslipSoFarPage.test.tsx (date 2026-11-10 -> 2026-11-02)
- frontend/src/theme.ts (full rewrite: exports `tokens` + `theme`)
- frontend/src/theme/colors.ts (info -> info palette)
- frontend/src/shell/AppShell.tsx (full rewrite: words-only nav, pill active,
  logo, use tokens)
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

# ---------- 1. PayslipSoFarPage.test.tsx: date picker ----------
test = SRC / "pages" / "PayslipSoFarPage.test.tsx"
s = test.read_text(encoding="utf-8")
s = s.replace('target: { value: "2026-11-10" }', 'target: { value: "2026-11-02" }')
s = s.replace('u.includes("as_of=2026-11-10")', 'u.includes("as_of=2026-11-02")')
test.write_text(s, encoding="utf-8")
print("PayslipSoFarPage.test.tsx: date picker target -> 2026-11-02")

# ---------- 2. theme.ts ----------
(SRC / "theme.ts").write_text('''import { createTheme } from "@mantine/core";

// Single source of colours, fonts, radii, shadows, spacing for the Mint look.
// Pages must not hard-code hexes; use tokens or Mantine CSS vars.

export const tokens = {
  pageBg: "#F3FBF7",
  cardBg: "#FFFFFF",
  text: "#0F2A24",
  muted: "#5B7A71",
  hairline: "#D5EBE2",
  menuBg: "#0F2A24",
  menuText: "#BFE8DA",
  menuMutedText: "rgba(191,232,218,0.55)",
  menuActiveBg: "#C9F3E0",
  menuActiveText: "#0B5A43",
  tile: {
    mint: { bg: "#C9F3E0", text: "#0B5A43" },
    yellow: { bg: "#FFE8A3", text: "#6B4E00" },
    lavender: { bg: "#DAD5FF", text: "#3B2F9E" },
    pink: { bg: "#FFD2DB", text: "#9A1F3E" },
  },
} as const;

// Mantine palettes tuned to hit the token values at the indexes Mantine uses.
// Index 7 = dark text / primary bg / light-variant text (primaryShade.light=7)
// Index 0 = very light bg for light-variant backgrounds
// Index 2 = tile background tints

export const theme = createTheme({
  primaryColor: "navy",
  primaryShade: { light: 7, dark: 5 },
  defaultRadius: "md",
  focusRing: "auto",
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
  fontFamilyMonospace:
    "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
  headings: {
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    fontWeight: "500",
    sizes: {
      h1: { fontSize: "2rem", lineHeight: "1.2", fontWeight: "500" },
      h2: { fontSize: "1.75rem", lineHeight: "1.25", fontWeight: "500" },
      h3: { fontSize: "1.25rem", lineHeight: "1.3", fontWeight: "500" },
    },
  },
  colors: {
    // Primary: dark green-black. Index 7 = #0F2A24 (button bg, side menu bg).
    navy: [
      "#F0F5F2", "#DCE7E1", "#B8CFC3", "#8DAF9E", "#668C7B",
      "#446858", "#1F4A3B", "#0F2A24", "#081612", "#030907",
    ],
    // Semantic "approved" = mint. Index 7 = #0B5A43, index 2 = #C9F3E0.
    approved: [
      "#F0FCF6", "#DCF6E9", "#C9F3E0", "#9FEBC9", "#6EDFAE",
      "#3FCE8F", "#24B270", "#0B5A43", "#083F2F", "#042A1F",
    ],
    // Semantic "pending" = yellow. Index 7 = #6B4E00, index 2 = #FFE8A3.
    pending: [
      "#FFFDF5", "#FFF5DC", "#FFE8A3", "#FFDA6E", "#FFCB3A",
      "#E8B41A", "#C89600", "#6B4E00", "#4A3500", "#2A1F00",
    ],
    // Semantic "problem" = pink. Index 7 = #9A1F3E, index 2 = #FFD2DB.
    problem: [
      "#FFF5F7", "#FFE0E6", "#FFD2DB", "#FFB0BF", "#FF8DA2",
      "#F06080", "#C93F5F", "#9A1F3E", "#6E1428", "#420B18",
    ],
    // Semantic "info" = lavender. Index 7 = #3B2F9E, index 2 = #DAD5FF.
    info: [
      "#F8F7FF", "#EDE9FF", "#DAD5FF", "#C0B8FF", "#A096FF",
      "#7C6EEB", "#5B4DCA", "#3B2F9E", "#2A2178", "#1A134E",
    ],
    // Accent kept for backwards-compat with colors.accent references.
    accent: [
      "#FFF5EB", "#FDE5C8", "#F8CC9A", "#F0B070", "#E89345",
      "#D97624", "#C45F22", "#A84E1B", "#7A3A14", "#4E250D",
    ],
  },
  radius: {
    xs: "4px",
    sm: "8px",
    md: "14px",
    lg: "18px",
    xl: "9999px",
  },
  shadows: {
    xs: "0 1px 2px rgba(15,42,36,0.04)",
    sm: "0 1px 2px rgba(15,42,36,0.06)",
    md: "0 2px 6px rgba(15,42,36,0.05)",
    lg: "0 4px 12px rgba(15,42,36,0.06)",
  },
  components: {
    Button: {
      defaultProps: { radius: "xl" },
    },
    Card: {
      defaultProps: { withBorder: true, radius: "md" },
      styles: {
        root: {
          borderColor: tokens.hairline,
          boxShadow: "none",
        },
      },
    },
    Paper: {
      defaultProps: { radius: "md" },
      styles: {
        root: { borderColor: tokens.hairline },
      },
    },
    Table: {
      defaultProps: {
        horizontalSpacing: "md",
        verticalSpacing: "sm",
        highlightOnHover: true,
      },
      styles: {
        th: {
          backgroundColor: "transparent",
          color: tokens.muted,
          fontWeight: 500,
          fontSize: 12,
          textTransform: "uppercase",
          letterSpacing: 0.3,
          borderBottom: `1px solid ${tokens.hairline}`,
        },
        td: {
          borderBottom: `1px solid ${tokens.hairline}`,
        },
        tr: {
          "&:hover": {
            backgroundColor: `${tokens.pageBg} !important`,
          },
        },
      },
    },
    Badge: {
      defaultProps: { radius: "sm" },
    },
    Modal: {
      defaultProps: { radius: "md", centered: true },
    },
    Alert: {
      defaultProps: { radius: "md" },
    },
    TextInput: { defaultProps: { radius: "md" } },
    Textarea: { defaultProps: { radius: "md" } },
    Select: { defaultProps: { radius: "md" } },
    MultiSelect: { defaultProps: { radius: "md" } },
    NumberInput: { defaultProps: { radius: "md" } },
    PasswordInput: { defaultProps: { radius: "md" } },
    Tabs: {
      styles: {
        tab: {
          "&[data-active]": {
            backgroundColor: tokens.tile.mint.bg,
            color: tokens.tile.mint.text,
          },
        },
      },
    },
  },
});
''', encoding="utf-8")
print("wrote theme.ts (tokens + theme)")

# ---------- 3. theme/colors.ts ----------
(SRC / "theme" / "colors.ts").write_text('''// Semantic colour aliases. Names resolve to Mantine palettes defined in theme.ts.
// Pages import this map; no page writes a literal hex again.
export const colors = {
  approved: "approved",
  pending: "pending",
  problem: "problem",
  inactive: "gray",
  info: "info",
  warning: "pending",
  accent: "accent",
} as const;

export type SemanticColor = (typeof colors)[keyof typeof colors];
''', encoding="utf-8")
print("wrote theme/colors.ts")

# ---------- 4. shell/AppShell.tsx ----------
(SRC / "shell" / "AppShell.tsx").write_text('''import { Link as RouterLink, Outlet, useLocation } from "react-router-dom";
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
                  {me.data?.username ?? "\\u2026"}
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
''', encoding="utf-8")
print("wrote shell/AppShell.tsx")

print("\nBundle complete.")