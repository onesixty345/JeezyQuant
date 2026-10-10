"use client";

import type { LeaderboardRow } from "@/lib/scoring";

function fmt(n: number | undefined, digits = 3): string {
  return n === undefined || Number.isNaN(n) ? "—" : n.toFixed(digits);
}

export default function Leaderboard({
  title,
  rows,
  tone,
}: {
  title: string;
  rows: LeaderboardRow[];
  tone: "bullish" | "bearish";
}) {
  const accent = tone === "bullish" ? "text-emerald-300" : "text-red-300";
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
      <h2 className={`text-lg font-semibold mb-3 ${accent}`}>{title}</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No scored tickers yet — add one below and wait for the next backend run.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-zinc-500 border-b border-zinc-800">
              <th className="py-2 pr-2">#</th>
              <th className="py-2 pr-2">Ticker</th>
              <th className="py-2 pr-2 text-right">Score</th>
              <th className="py-2 pr-2 text-right">Divergence</th>
              <th className="py-2 pr-2 text-right">Vol cluster</th>
              <th className="py-2 text-right">As of</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 10).map((t, i) => (
              <tr key={t.symbol} className="border-b border-zinc-800/60 last:border-0">
                <td className="py-2 pr-2 text-zinc-500">{i + 1}</td>
                <td className="py-2 pr-2 font-mono font-semibold">{t.symbol}</td>
                <td className="py-2 pr-2 text-right font-mono">{fmt(t.compositeScore)}</td>
                <td className="py-2 pr-2 text-right font-mono">{fmt(t.divergenceSpread)}</td>
                <td className="py-2 pr-2 text-right font-mono">{fmt(t.volatilityCluster)}</td>
                <td className="py-2 text-right text-zinc-500">{t.dataAsOf ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
