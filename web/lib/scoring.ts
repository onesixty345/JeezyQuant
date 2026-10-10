// Scoring — kept transparent by design.
//
// The backend stores RAW factors per ticker (volatilityCluster, divergenceSpread)
// and refreshes a denormalized /quant/leaderboard node each run — the only node
// the UI reads (tiny; histories stay server-side).
// compositeScore = z(divergenceSpread) + z(volatilityCluster) across the tracked
// universe. Equal weighting, documented here — not a tuned model. The raw factors
// live independently in RTDB so a trained classifier can replace this later.

export interface LeaderboardRow {
  symbol: string;
  companyName?: string;
  compositeScore?: number;
  volatilityCluster?: number; // 0..1
  divergenceSpread?: number; // decimals: stock 90d return − supplier revenue YoY
  dataAsOf?: string;
}

export function sortBullish(rows: LeaderboardRow[]): LeaderboardRow[] {
  return [...rows].sort((a, b) => (a.compositeScore ?? 0) - (b.compositeScore ?? 0));
}

export function sortBearish(rows: LeaderboardRow[]): LeaderboardRow[] {
  return [...rows].sort((a, b) => (b.compositeScore ?? 0) - (a.compositeScore ?? 0));
}
