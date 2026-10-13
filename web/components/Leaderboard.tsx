"use client";

import { useEffect, useState } from "react";
import type { LeaderboardRow } from "@/lib/scoring";

function fmt(n: number | undefined, digits = 3): string {
  return n === undefined || Number.isNaN(n) ? "—" : n.toFixed(digits);
}

interface ColumnInfo {
  key: string;
  label: string;
  plain: string;
  technical: string;
}

// Simple names up front; the technical terms live inside the modal.
const COLUMNS: ColumnInfo[] = [
  {
    key: "score",
    label: "Score",
    plain:
      "The stock's overall grade. It blends the two checks below and ranks " +
      "every tracked stock against each other. Higher means stronger — " +
      "that's why the biggest numbers sit at the top of the bullish board.",
    technical:
      "compositeScore = z-score(divergenceSpread) + z-score(volatilityCluster), " +
      "equal-weighted across the tracked universe.",
  },
  {
    key: "story",
    label: "Story check",
    plain:
      "Does the company's money story match its stock price? A positive " +
      "number means the stock has been running ahead of sales growth; a " +
      "negative number means it's lagging behind. Big gaps in either " +
      "direction are worth a closer look.",
    technical:
      "divergenceSpread = 90-day trailing stock return minus year-over-year " +
      "revenue growth (supplier average when suppliers are tracked, " +
      "otherwise the company's own revenue).",
  },
  {
    key: "jumpiness",
    label: "Jumpiness",
    plain:
      "How wild the price swings have been lately, from 0 (calm) to 1 " +
      "(stormy), compared to this stock's own history. Jumpiness comes in " +
      "clusters — calm stretches tend to follow calm stretches, and shaky " +
      "ones follow shaky ones.",
    technical:
      "volatilityCluster = percentile rank of the 63-day rolling standard " +
      "deviation of log returns versus full history. Under 126 days of " +
      "history it defaults to 0.5 (neutral).",
  },
  {
    key: "asof",
    label: "Data date",
    plain:
      "The latest trading day counted in these numbers. When this date " +
      "gets old, the STALE banner appears at the top of the page.",
    technical: "dataAsOf — the newest date key in the ticker's stored price history.",
  },
];

function InfoModal({ info, onClose }: { info: ColumnInfo; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`${info.label} explained`}
    >
      <div
        className="w-full max-w-md rounded-lg border border-zinc-700 bg-zinc-900 p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <h3 className="text-base font-semibold text-zinc-100">{info.label}</h3>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded px-2 py-0.5 text-xl leading-none text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
          >
            ×
          </button>
        </div>
        <p className="mt-3 text-sm leading-relaxed text-zinc-300">{info.plain}</p>
        <details className="mt-4 rounded border border-zinc-800 bg-zinc-950/60 p-3">
          <summary className="cursor-pointer text-xs font-medium uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
            Technical details
          </summary>
          <p className="mt-2 font-mono text-xs leading-relaxed text-zinc-400">
            {info.technical}
          </p>
        </details>
      </div>
    </div>
  );
}

function HeaderCell({
  info,
  align = "left",
  onInfo,
}: {
  info: ColumnInfo;
  align?: "left" | "right";
  onInfo: (info: ColumnInfo) => void;
}) {
  return (
    <th className={`py-2 pr-2 ${align === "right" ? "text-right" : "text-left"}`}>
      <button
        onClick={() => onInfo(info)}
        title={`What does ${info.label} mean?`}
        className="group inline-flex items-center gap-1 hover:text-zinc-200"
      >
        <span className="underline decoration-dotted decoration-zinc-600 underline-offset-4 group-hover:decoration-zinc-300">
          {info.label}
        </span>
        <span
          aria-hidden="true"
          className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-zinc-600 text-[10px] leading-none text-zinc-500 group-hover:border-zinc-300 group-hover:text-zinc-200"
        >
          i
        </span>
      </button>
    </th>
  );
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
  const [activeInfo, setActiveInfo] = useState<ColumnInfo | null>(null);
  const accent = tone === "bullish" ? "text-emerald-300" : "text-red-300";
  const byKey = Object.fromEntries(COLUMNS.map((c) => [c.key, c]));

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
            <tr className="text-zinc-500 border-b border-zinc-800">
              <th className="py-2 pr-2 text-left">#</th>
              <th className="py-2 pr-2 text-left">Ticker</th>
              <HeaderCell info={byKey.score} align="right" onInfo={setActiveInfo} />
              <HeaderCell info={byKey.story} align="right" onInfo={setActiveInfo} />
              <HeaderCell info={byKey.jumpiness} align="right" onInfo={setActiveInfo} />
              <HeaderCell info={byKey.asof} align="right" onInfo={setActiveInfo} />
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
      {activeInfo && <InfoModal info={activeInfo} onClose={() => setActiveInfo(null)} />}
    </section>
  );
}
