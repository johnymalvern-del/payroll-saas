// Semantic color aliases. These names live only here and in theme.ts.
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
