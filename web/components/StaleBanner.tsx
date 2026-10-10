"use client";

import { useEffect, useState } from "react";
import { child, get, ref } from "firebase/database";
import { rtdb } from "@/lib/firebase";

const STALE_HOURS = 24;

export default function StaleBanner() {
  const [stale, setStale] = useState<boolean | null>(null);
  const [lastRun, setLastRun] = useState<string>("");

  useEffect(() => {
    (async () => {
      try {
        const snap = await get(child(ref(rtdb), "quant/config/global/lastSuccessfulRun"));
        const ms: number | null = snap.val();
        if (!ms) {
          setStale(true);
          return;
        }
        const d = new Date(ms);
        setLastRun(d.toLocaleString());
        setStale(Date.now() - ms > STALE_HOURS * 3600 * 1000);
      } catch {
        setStale(true); // cannot verify freshness → treat as stale, say so
      }
    })();
  }, []);

  if (stale === null) return null;
  if (!stale)
    return (
      <div className="rounded-md bg-emerald-900/40 border border-emerald-700 px-4 py-2 text-sm text-emerald-200">
        Data fresh — last backend run {lastRun}.
      </div>
    );
  return (
    <div className="rounded-md bg-red-900/50 border border-red-600 px-4 py-3 text-sm text-red-100">
      <strong>STALE</strong> — the backend has not completed a run in over{" "}
      {STALE_HOURS} hours{lastRun ? ` (last run ${lastRun})` : ""}. Scores below
      may not reflect current market data.
    </div>
  );
}
