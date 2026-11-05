// Semantic colour aliases (resolve to Mantine palettes in theme.ts).
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
