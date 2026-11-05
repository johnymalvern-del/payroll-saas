import { createTheme } from "@mantine/core";

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
