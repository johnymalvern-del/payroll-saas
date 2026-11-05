import { createTheme } from "@mantine/core";

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
