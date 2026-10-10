"use client";

import { useCallback, useEffect, useState } from "react";
import { child, get, ref } from "firebase/database";
import { getRtdb } from "@/lib/firebase";
import { sortBearish, sortBullish, type LeaderboardRow } from "@/lib/scoring";
import StaleBanner from "@/components/StaleBanner";
import Leaderboard from "@/components/Leaderboard";
import AddTicker from "@/components/AddTicker";
import AuthGate from "@/components/AuthGate";

function DashboardContent() {
  const [rows, setRows] = useState<LeaderboardRow[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      // Reads ONLY the denormalized leaderboard node — never the 2-yr histories.
      const snap = await get(child(ref(getRtdb()), "quant/leaderboard"));
      const val = snap.val() ?? {};
      setRows(
        Object.entries(val).map(([symbol, r]) => ({
          symbol,
          ...((r as object) ?? {}),
        })) as LeaderboardRow[]
      );
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold">Quant Dashboard</h1>
        <p className="text-sm text-zinc-500">
          Divergence &amp; volatility signals — research screening only, not trading advice.
        </p>
      </header>

      <StaleBanner />

      <AddTicker onAdded={refresh} />

      {loading ? (
        <p className="text-sm text-zinc-500">Loading tickers…</p>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          <Leaderboard title="Top 10 Bullish" rows={sortBullish(rows)} tone="bullish" />
          <Leaderboard title="Top 10 Bearish" rows={sortBearish(rows)} tone="bearish" />
        </div>
      )}

      <footer className="text-xs text-zinc-600">
        Scores are transparent z-score composites of raw stored factors — see docs.
        Execution stays manual.
      </footer>
    </main>
  );
}

export default function Dashboard() {
  return (
    <AuthGate>
      <DashboardContent />
    </AuthGate>
  );
}
