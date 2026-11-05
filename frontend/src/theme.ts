import { createTheme } from "@mantine/core";

// Single source of colours, fonts, radius, shadows, spacing.
// Every page uses semantic names from theme/colors.ts — no literals elsewhere.

export const theme = createTheme({
  primaryColor: "navy",
  primaryShade: { light: 7, dark: 5 },
  defaultRadius: "md",
  focusRing: "auto",
  fontFamily:
    "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
  fontFamilyMonospace:
    "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
  headings: {
    fontFamily:
      "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    fontWeight: "600",
    sizes: {
      h1: { fontSize: "1.75rem", lineHeight: "1.25", fontWeight: "600" },
      h2: { fontSize: "1.375rem", lineHeight: "1.3", fontWeight: "600" },
      h3: { fontSize: "1.125rem", lineHeight: "1.35", fontWeight: "600" },
    },
  },
  colors: {
    navy: [
      "#E6EEF3", "#C2D6E3", "#9DBDCF", "#5B8DAF",
      "#2E688F", "#0B3D5C", "#0A3651", "#082C43",
      "#062235", "#041927",
    ],
    accent: [
      "#FDF1E7", "#FAE2CC", "#F5C4A0", "#EFA570",
      "#EA8643", "#C45F22", "#AF531D", "#8F4317",
      "#713510", "#522608",
    ],
    approved: [
      "#E7F8EE", "#C6EED4", "#A2E3B8", "#7AD89B",
      "#57CD7F", "#2EA85B", "#1F8A47", "#186F39",
      "#12552B", "#0B3B1D",
    ],
    pending: [
      "#FFF4E0", "#FFE4B8", "#FFD28C", "#FFBD5C",
      "#FFA92E", "#D98600", "#B06B00", "#855100",
      "#593700", "#2C1C00",
    ],
    problem: [
      "#FDECEE", "#FAC8CD", "#F5A0A9", "#EE7482",
      "#E64B5E", "#C42B3D", "#A02030", "#7C1826",
      "#59101B", "#2D0810",
    ],
  },
  shadows: {
    xs: "0 1px 2px rgba(15, 23, 42, 0.04)",
    sm: "0 1px 2px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.04)",
    md: "0 4px 12px rgba(15, 23, 42, 0.08)",
    lg: "0 12px 32px rgba(15, 23, 42, 0.10)",
  },
  components: {
    Button: { defaultProps: { radius: "md" } },
    Paper: { defaultProps: { radius: "md" } },
    Card: { defaultProps: { radius: "md", shadow: "sm", padding: "lg" } },
    Badge: { defaultProps: { radius: "sm" } },
    Modal: { defaultProps: { radius: "md", centered: true } },
    Alert: { defaultProps: { radius: "md" } },
    Table: {
      defaultProps: {
        horizontalSpacing: "md",
        verticalSpacing: "sm",
        highlightOnHover: true,
      },
      styles: {
        th: {
          backgroundColor: "#F7F8FA",
          color: "#475569",
          fontWeight: 600,
          fontSize: 12,
          textTransform: "uppercase",
          letterSpacing: 0.4,
        },
      },
    },
  },
});
