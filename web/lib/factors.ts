// Pure-math factor computation — ported from modal/quant_job.py.
// Used to score a newly added ticker immediately from its cached (as-of)
// data, with zero FMP calls. The daily cron refreshes everything when new
// market data is available. forwardVolRatio (TimesFM) stays null until the
// cron fills it in; the composite z-score only uses divergence + volatility.

export function realizedVolPercentile(closes: number[]): number {
  if (closes.length < 126) return 0.5;
  const lr: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    lr.push(Math.log(closes[i] / closes[i - 1]));
  }
  const roll: number[] = [];
  for (let i = 63; i <= lr.length; i++) {
    const w = lr.slice(i - 63, i);
    const mu = w.reduce((a, b) => a + b, 0) / w.length;
    const sd = Math.sqrt(w.reduce((a, b) => a + (b - mu) ** 2, 0) / w.length);
    roll.push(sd);
  }
  const last = roll[roll.length - 1];
  return roll.filter((v) => v < last).length / roll.length;
}

export function trailingReturn(closes: number[], days = 90): number {
  if (closes.length < 2) return 0.0;
  const n = Math.min(days + 1, closes.length);
  return closes[closes.length - 1] / closes[closes.length - n] - 1.0;
}

export function yoyGrowth(
  quarters: { revenue: number }[]
): number | null {
  if (quarters.length < 5) return null;
  const newest = quarters[0].revenue;
  const yearAgo = quarters[4].revenue;
  if (!newest || !yearAgo) return null;
  return newest / yearAgo - 1.0;
}

export function zscores(values: number[]): number[] {
  if (values.length === 0) return [];
  const mu = values.reduce((a, b) => a + b, 0) / values.length;
  const sd = Math.sqrt(
    values.reduce((a, b) => a + (b - mu) ** 2, 0) / values.length
  );
  if (sd < 1e-12) return values.map(() => 0.0);
  return values.map((v) => (v - mu) / sd);
}

export function sortedQuarters<T extends { period: string }>(
  revMap: Record<string, Omit<T, "period">>
): T[] {
  return (Object.entries(revMap) as [string, Omit<T, "period">][])
    .map(([period, v]) => ({ period, ...v } as T))
    .sort((a, b) => (a.period < b.period ? 1 : a.period > b.period ? -1 : 0));
}
