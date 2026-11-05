"""P1a: theme, colors module, layout components, main.tsx force-light, strings."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

# --- 1. colors.ts ---
(SRC / "theme").mkdir(exist_ok=True)
(SRC / "theme" / "colors.ts").write_text('''// Semantic color aliases. These names live only here and in theme.ts.
// Pages import this map; no page writes a literal color name again.
export const colors = {
  approved: "approved",
  pending: "pending",
  problem: "problem",
  inactive: "gray",
  info: "navy",
  warning: "pending",
  accent: "accent",
} as const;

export type SemanticColor = (typeof colors)[keyof typeof colors];
''', encoding="utf-8")
print("wrote src/theme/colors.ts")

# --- 2. theme.ts (backup original if present) ---
theme_path = SRC / "theme.ts"
if theme_path.exists():
    (SRC / "theme.backup.ts").write_text(theme_path.read_text(encoding="utf-8"), encoding="utf-8")
    print("backed up theme.ts -> theme.backup.ts")

theme_path.write_text('''import { createTheme } from "@mantine/core";

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
''', encoding="utf-8")
print("wrote src/theme.ts")

# --- 3. Icon.tsx ---
layout_dir = SRC / "components" / "layout"
layout_dir.mkdir(parents=True, exist_ok=True)

(layout_dir / "Icon.tsx").write_text('''export type IconName =
  | "home" | "calendar" | "alert" | "sliders" | "clock" | "users"
  | "dollar" | "check" | "file" | "settings" | "audit" | "logout";

const PATHS: Record<IconName, string> = {
  home: "M3 9.5L12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-7h-6v7H4a1 1 0 0 1-1-1V9.5z",
  calendar:
    "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
  alert:
    "M12 9v4M12 17h.01M10.3 3.9L2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  sliders:
    "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6",
  clock: "M12 6v6l4 2M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z",
  users:
    "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  dollar: "M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6",
  check: "M22 11.1V12a10 10 0 1 1-5.9-9.1M22 4L12 14.01l-3-3",
  file:
    "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8",
  settings:
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
  audit:
    "M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
};

export function Icon({
  name,
  size = 18,
  color = "currentColor",
}: {
  name: IconName;
  size?: number;
  color?: string;
}) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
''', encoding="utf-8")
print("wrote src/components/layout/Icon.tsx")

# --- 4. PageHeader ---
(layout_dir / "PageHeader.tsx").write_text('''import { Group, Stack, Title, Text } from "@mantine/core";
import type { ReactNode } from "react";

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <Group justify="space-between" align="flex-start" wrap="wrap" mb="md">
      <Stack gap={2}>
        <Title order={2}>{title}</Title>
        {subtitle ? (
          <Text size="sm" c="dimmed">
            {subtitle}
          </Text>
        ) : null}
      </Stack>
      {actions ? <Group gap="sm">{actions}</Group> : null}
    </Group>
  );
}
''', encoding="utf-8")
print("wrote src/components/layout/PageHeader.tsx")

# --- 5. EmptyState ---
(layout_dir / "EmptyState.tsx").write_text('''import { Paper, Stack, Text } from "@mantine/core";

export function EmptyState({ message }: { message: string }) {
  return (
    <Paper p="xl" withBorder style={{ textAlign: "center" }}>
      <Stack gap="xs" align="center">
        <Text c="dimmed" size="sm">
          {message}
        </Text>
      </Stack>
    </Paper>
  );
}
''', encoding="utf-8")
print("wrote src/components/layout/EmptyState.tsx")

# --- 6. TableSkeleton ---
(layout_dir / "TableSkeleton.tsx").write_text('''import { Skeleton, Table } from "@mantine/core";

export function TableSkeleton({ rows = 6, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          {Array.from({ length: cols }, (_, i) => (
            <Table.Th key={i}>
              <Skeleton height={10} width={80} />
            </Table.Th>
          ))}
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {Array.from({ length: rows }, (_, r) => (
          <Table.Tr key={r}>
            {Array.from({ length: cols }, (_, c) => (
              <Table.Td key={c}>
                <Skeleton height={14} />
              </Table.Td>
            ))}
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
''', encoding="utf-8")
print("wrote src/components/layout/TableSkeleton.tsx")

# --- 7. main.tsx: force light color scheme (design is light-only for now) ---
main = SRC / "main.tsx"
m = main.read_text(encoding="utf-8")
if 'forceColorScheme="light"' in m:
    print("main.tsx: forceColorScheme already set")
elif 'defaultColorScheme="auto"' in m:
    m = m.replace('defaultColorScheme="auto"', 'defaultColorScheme="light"', 1)
    main.write_text(m, encoding="utf-8")
    print("main.tsx: defaultColorScheme auto -> light")
else:
    print("main.tsx: WARN — color scheme attr not found (leave unchanged)")

# --- 8. strings.ts: add nav + empty + pageHeader blocks ---
strings = SRC / "lib" / "strings.ts"
s = strings.read_text(encoding="utf-8")
if "nav: {" in s:
    print("strings.ts: nav block already present")
else:
    blocks = '''  nav: {
    home: "Home",
    attendanceSheet: "Attendance sheet",
    exceptions: "Exceptions",
    adjustments: "Adjustments",
    clockIn: "Clock in",
    employees: "Employees",
    payPeriods: "Pay periods",
    changeRequests: "Change requests",
    payslips: "My payslips",
    setup: "Setup",
    auditLog: "Audit log",
    sectionAttendance: "Attendance",
    sectionPeople: "People",
    sectionPayroll: "Payroll",
    sectionSetup: "Setup",
    sectionAudit: "Audit",
  },
  empty: {
    default: "Nothing here yet.",
    noRows: "No rows to show.",
  },
'''
    s = s.replace("export const strings = {\n", "export const strings = {\n" + blocks, 1)
    strings.write_text(s, encoding="utf-8")
    print("strings.ts: nav + empty blocks added")