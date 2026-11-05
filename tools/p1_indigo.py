"""Palette redesign: Indigo Ledger. Same layout, same test ids, new colours."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

# ---------- 1. theme.ts (full rewrite) ----------
(SRC / "theme.ts").write_text('''import { createTheme } from "@mantine/core";

// "Indigo Ledger" — modern fintech palette.
// Single source of colours, fonts, radii. Pages must not hard-code hexes.

export const tokens = {
  pageBg: "#F7F6F3",            // warm cream
  cardBg: "#FFFFFF",
  text: "#0F172A",              // ink
  muted: "#64748B",             // slate
  hairline: "#E2E8F0",

  menuBgFrom: "#171233",        // deep indigo-black
  menuBgTo: "#0E0A20",          // deeper violet-black
  menuText: "#A5A3B8",          // muted lavender-grey
  menuMutedText: "#6B6883",     // section labels
  menuActiveFrom: "#4F46E5",    // indigo
  menuActiveTo: "#7C3AED",      // violet
  menuActiveText: "#FFFFFF",

  logoFrom: "#6366F1",
  logoTo: "#8B5CF6",

  tile: {
    mint: { bg: "#C7F0E5", text: "#115E52" },      // teal (not green)
    yellow: { bg: "#FDE68A", text: "#78350F" },    // honey
    lavender: { bg: "#DDD6FE", text: "#4C1D95" },  // vivid violet
    pink: { bg: "#FECDD3", text: "#881337" },      // rose
  },
} as const;

export const theme = createTheme({
  primaryColor: "navy",
  primaryShade: { light: 6, dark: 4 },
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
    // Primary: rich indigo. Index 6 = #4F46E5 (filled Button bg).
    navy: [
      "#EEF2FF", "#E0E7FF", "#C7D2FE", "#A5B4FC", "#818CF8",
      "#6366F1", "#4F46E5", "#4338CA", "#3730A3", "#312E81",
    ],
    // Semantic "approved" = teal. Index 7 = #0F766E, index 2 = #99F6E4.
    approved: [
      "#F0FDFA", "#CCFBF1", "#99F6E4", "#5EEAD4", "#2DD4BF",
      "#14B8A6", "#0D9488", "#0F766E", "#115E59", "#134E4A",
    ],
    // Semantic "pending" = honey/amber. Index 7 = #B45309, index 2 = #FDE68A.
    pending: [
      "#FFFBEB", "#FEF3C7", "#FDE68A", "#FCD34D", "#FBBF24",
      "#F59E0B", "#D97706", "#B45309", "#92400E", "#78350F",
    ],
    // Semantic "problem" = rose. Index 7 = #BE123C, index 2 = #FECDD3.
    problem: [
      "#FFF1F2", "#FFE4E6", "#FECDD3", "#FDA4AF", "#FB7185",
      "#F43F5E", "#E11D48", "#BE123C", "#9F1239", "#881337",
    ],
    // Semantic "info" = violet. Index 7 = #6D28D9, index 2 = #DDD6FE.
    info: [
      "#F5F3FF", "#EDE9FE", "#DDD6FE", "#C4B5FD", "#A78BFA",
      "#8B5CF6", "#7C3AED", "#6D28D9", "#5B21B6", "#4C1D95",
    ],
    // Accent kept for backwards-compat.
    accent: [
      "#FFF7ED", "#FFEDD5", "#FED7AA", "#FDBA74", "#FB923C",
      "#F97316", "#EA580C", "#C2410C", "#9A3412", "#7C2D12",
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
    xs: "0 1px 2px rgba(15,23,42,0.04)",
    sm: "0 1px 2px rgba(15,23,42,0.06)",
    md: "0 2px 6px rgba(15,23,42,0.05)",
    lg: "0 4px 12px rgba(15,23,42,0.06)",
  },
  components: {
    Button: { defaultProps: { radius: "xl" } },
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
      styles: { root: { borderColor: tokens.hairline } },
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
        td: { borderBottom: `1px solid ${tokens.hairline}` },
        tr: {
          "&:hover": {
            backgroundColor: `${tokens.pageBg} !important`,
          },
        },
      },
    },
    Badge: { defaultProps: { radius: "sm" } },
    Modal: { defaultProps: { radius: "md", centered: true } },
    Alert: { defaultProps: { radius: "md" } },
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
            backgroundColor: tokens.tile.lavender.bg,
            color: tokens.tile.lavender.text,
          },
        },
      },
    },
  },
});

// Global body background — makes login page and any page outside AppShell
// pick up the cream page colour.
export const cssVariablesResolver = () => ({
  variables: {
    "--mantine-color-body": tokens.pageBg,
  },
  light: {},
  dark: {},
});
''', encoding="utf-8")
print("wrote theme.ts (Indigo Ledger)")

# ---------- 2. theme/colors.ts (unchanged logic; refreshed comment) ----------
(SRC / "theme" / "colors.ts").write_text('''// Semantic colour aliases (resolve to Mantine palettes in theme.ts).
// Pages import this map; no page writes a literal hex.
export const colors = {
  approved: "approved",   // teal
  pending: "pending",     // honey
  problem: "problem",     // rose
  inactive: "gray",
  info: "info",           // violet
  warning: "pending",
  accent: "accent",       // orange
} as const;

export type SemanticColor = (typeof colors)[keyof typeof colors];
''', encoding="utf-8")
print("wrote theme/colors.ts")

# ---------- 3. shell/AppShell.tsx ----------
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
                    width: 32,
                    height: 32,
                    borderRadius: 10,
                    background: `linear-gradient(135deg, ${tokens.logoFrom} 0%, ${tokens.logoTo} 100%)`,
                    color: "#FFFFFF",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 700,
                    fontSize: 15,
                    letterSpacing: 0.5,
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
          background: `linear-gradient(180deg, ${tokens.menuBgFrom} 0%, ${tokens.menuBgTo} 100%)`,
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
                      letterSpacing: 0.6,
                      fontSize: 10,
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
                        padding: "10px 16px",
                        borderRadius: 999,
                        background: active
                          ? `linear-gradient(135deg, ${tokens.menuActiveFrom} 0%, ${tokens.menuActiveTo} 100%)`
                          : "transparent",
                        color: active
                          ? tokens.menuActiveText
                          : tokens.menuText,
                        fontWeight: active ? 600 : 400,
                        fontSize: 14,
                        transition: "background-color 120ms ease",
                        boxShadow: active
                          ? "0 2px 8px rgba(99,102,241,0.35)"
                          : "none",
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

# ---------- 4. main.tsx: cssVariablesResolver ----------
main = SRC / "main.tsx"
s = main.read_text(encoding="utf-8")

if "cssVariablesResolver" in s:
    print("main.tsx: cssVariablesResolver already imported")
else:
    # update import from theme
    if 'import { theme } from "./theme";' in s:
        s = s.replace(
            'import { theme } from "./theme";',
            'import { cssVariablesResolver, theme } from "./theme";',
            1,
        )
        print("main.tsx: cssVariablesResolver import added")
    else:
        raise SystemExit("FATAL: theme import not matched")

    if "<MantineProvider theme={theme}" in s and "cssVariablesResolver=" not in s:
        s = s.replace(
            "<MantineProvider theme={theme}",
            "<MantineProvider cssVariablesResolver={cssVariablesResolver} theme={theme}",
            1,
        )
        print("main.tsx: cssVariablesResolver prop added")

main.write_text(s, encoding="utf-8")

print("\nPalette swap complete.")