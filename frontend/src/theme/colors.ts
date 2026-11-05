// Semantic colour aliases. Names resolve to Mantine palettes defined in theme.ts.
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
