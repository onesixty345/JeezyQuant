import { NextResponse } from "next/server";
import { adminDb, adminAuth, isAllowlisted } from "@/lib/admin";
import {
  realizedVolPercentile,
  trailingReturn,
  yoyGrowth,
  zscores,
  sortedQuarters,
} from "@/lib/factors";

// POST /api/tickers { symbol: "MU" } + Authorization: Bearer <Firebase ID token>
// 1. Verifies the caller's Firebase ID token and allowlist membership.
// 2. Validates the symbol; skips if already active/queued (idempotent).
// 3. Writes /quant/tickers/{SYMBOL}/meta status "backfill_queued" via Admin SDK.
// 4. Triggers the secured Modal backfill endpoint (x-backfill-secret header).
// 5. Scores the ticker immediately from its cached as-of data (zero FMP calls):
//    volatility + divergence factors, then z-score composite + leaderboard
//    refresh across the full universe. forwardVolRatio (TimesFM) is filled in
//    by the daily cron.
//
// No market-data API calls happen here — the Modal backend owns all provider calls.

const MODAL_BACKFILL_URL = process.env.MODAL_BACKFILL_URL;
const BACKFILL_SECRET = process.env.MODAL_BACKFILL_SECRET;

export async function POST(req: Request) {
  try {
    // --- 1. Caller auth ---
    const m = (req.headers.get("authorization") ?? "").match(/^Bearer (.+)$/);
    if (!m) {
      return NextResponse.json({ error: "Not signed in." }, { status: 401 });
    }
    let email: string | undefined;
    try {
      const decoded = await adminAuth().verifyIdToken(m[1]);
      email = decoded.email;
    } catch (e) {
      const code = e instanceof Error && "code" in e ? String((e as { code: unknown }).code) : "unknown";
      return NextResponse.json(
        { error: `Invalid session (${code}). Sign in again.` },
        { status: 401 }
      );
    }
    if (!isAllowlisted(email)) {
      return NextResponse.json({ error: "Not authorized." }, { status: 403 });
    }

    // --- 2. Validate ---
    const { symbol } = await req.json();
    const clean = typeof symbol === "string" ? symbol.trim().toUpperCase() : "";
    if (!/^[A-Z.]{1,10}$/.test(clean)) {
      return NextResponse.json({ error: "Invalid ticker symbol." }, { status: 400 });
    }
    if (!MODAL_BACKFILL_URL || !BACKFILL_SECRET) {
      return NextResponse.json(
        { error: "Backend not configured (missing env vars)." },
        { status: 503 }
      );
    }

    const db = adminDb();
    const metaRef = db.ref(`quant/tickers/${clean}/meta`);
    const existingStatus = ((await metaRef.get()).val() as { status?: string } | null)
      ?.status;
    if (existingStatus === "active" || existingStatus === "backfill_queued") {
      return NextResponse.json({ symbol: clean, status: existingStatus });
    }

    // --- 3. Queue ---
    await metaRef.set({
      symbol: clean,
      status: "backfill_queued",
      queuedAt: Date.now(),
      queuedBy: email,
    });

    // --- 4. Trigger Modal backfill ---
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 55000);
    try {
      const r = await fetch(MODAL_BACKFILL_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-backfill-secret": BACKFILL_SECRET,
        },
        body: JSON.stringify({
          symbol: clean,
          secret: BACKFILL_SECRET,
          suppliers: [],
        }),
        signal: controller.signal,
      });
      const data = (await r.json()) as {
        status?: string;
        bars?: number;
        calls?: number;
        reason?: string;
      };
      if (data?.status === "ok") {
        // --- 5. Score immediately from cached as-of data (no FMP calls) ---
        const scored = await scoreTickerFromCache(db, clean);
        return NextResponse.json({
          symbol: clean,
          status: "active",
          bars: data.bars,
          calls: data.calls,
          ...(scored
            ? {
                volatilityCluster: scored.volatilityCluster,
                divergenceSpread: scored.divergenceSpread,
                compositeScore: scored.compositeScore,
                universeSize: scored.universeSize,
              }
            : { note: "Backfilled; scoring on next backend run." }),
        });
      }
      await metaRef.update({
        status: "backfill_failed",
        error: String(data?.reason ?? "unknown").slice(0, 300),
      });
      return NextResponse.json(
        { symbol: clean, status: "backfill_failed", reason: data?.reason },
        { status: 502 }
      );
    } catch (e) {
      // Timeout / network error: backfill may still be running server-side.
      const note = e instanceof Error ? e.message : "request failed";
      await metaRef.update({
        status: "backfill_queued",
        note: note.slice(0, 200),
      });
      return NextResponse.json(
        {
          symbol: clean,
          status: "backfill_queued",
          note: "Still running — refresh shortly.",
        },
        { status: 202 }
      );
    } finally {
      clearTimeout(timeout);
    }
  } catch {
    return NextResponse.json({ error: "Bad request." }, { status: 400 });
  }
}

// Score a ticker from its cached RTDB data — zero FMP calls. Computes the
// pure-math factors (volatility cluster, divergence spread), writes them,
// then recomputes the z-score composite + leaderboard across the full
// universe so the new ticker ranks immediately. Returns null if there isn't
// enough cached history yet (the daily cron will score it later).
async function scoreTickerFromCache(
  db: import("firebase-admin").database.Database,
  symbol: string
): Promise<{
  volatilityCluster: number;
  divergenceSpread: number;
  compositeScore: number;
  universeSize: number;
} | null> {
  const snap = await db.ref(`quant/tickers/${symbol}`).get();
  const node = (snap.val() as Record<string, unknown> | null) ?? {};
  const hist = (node.priceHistory as Record<string, { close: number }>) ?? {};
  const dates = Object.keys(hist).sort();
  if (dates.length < 60) return null;
  const closes = dates.map((d) => hist[d].close);

  const revMap = (node.revenueQuarterly as Record<string, { revenue: number }>) ?? {};
  const supNodes =
    (node.suppliers as Record<string, { revenueQuarterly?: Record<string, { revenue: number }> }>) ?? {};

  const vol = realizedVolPercentile(closes);
  const ret90 = trailingReturn(closes, 90);

  const supYoys: number[] = [];
  for (const sup of Object.keys(supNodes).slice(0, 2)) {
    const sq = sortedQuarters<{ period: string; revenue: number }>(
      supNodes[sup].revenueQuarterly ?? {}
    );
    const g = yoyGrowth(sq);
    if (g !== null) supYoys.push(g);
  }
  const ownYoy = yoyGrowth(
    sortedQuarters<{ period: string; revenue: number }>(revMap)
  );
  const divBase = supYoys.length > 0
    ? supYoys.reduce((a, b) => a + b, 0) / supYoys.length
    : ownYoy;
  const divergence = ret90 - (divBase ?? 0.0);

  const now = Date.now();
  const meta = (node.meta as { companyName?: string; dataAsOf?: string }) ?? {};
  await db.ref(`quant/tickers/${symbol}`).update({
    "meta/lastUpdated": now,
    "meta/consecutiveFailures": 0,
    factors: {
      computedAt: now,
      modelCheckpoint: "on-add",
      horizonDays: 30,
      volatilityCluster: vol,
      divergenceSpread: divergence,
      forwardVolRatio: null,
    },
  });

  // Recompute z-scores across every ticker that has factors.
  const allSnap = await db.ref("quant/tickers").get();
  const all = (allSnap.val() as Record<string, Record<string, unknown>>) ?? {};
  const scored: {
    s: string; company: string; div: number; vol: number;
    fwd: number | null; asof?: string;
  }[] = [];
  for (const [s, d] of Object.entries(all)) {
    const f = (d.factors as { volatilityCluster?: number; divergenceSpread?: number; forwardVolRatio?: number | null }) ?? {};
    if (typeof f.volatilityCluster !== "number" || typeof f.divergenceSpread !== "number") continue;
    const m = (d.meta as { companyName?: string; dataAsOf?: string }) ?? {};
    scored.push({
      s, company: m.companyName ?? s, div: f.divergenceSpread,
      vol: f.volatilityCluster, fwd: f.forwardVolRatio ?? null, asof: m.dataAsOf,
    });
  }
  if (scored.length === 0) return null;

  const zdiv = zscores(scored.map((x) => x.div));
  const zvol = zscores(scored.map((x) => x.vol));
  const lb: Record<string, unknown> = {};
  const runId = `add-${now}`;
  scored.forEach((t, i) => {
    const comp = zdiv[i] + zvol[i];
    lb[`quant/tickers/${t.s}/factors/compositeScore`] = comp;
    lb[`quant/tickers/${t.s}/factorHistory/${runId}_${t.s}`] = {
      computedAt: now,
      modelCheckpoint: "on-add",
      volatilityCluster: t.vol,
      divergenceSpread: t.div,
      forwardVolRatio: t.fwd,
      compositeScore: comp,
    };
    lb[`quant/leaderboard/${t.s}`] = {
      symbol: t.s,
      companyName: t.company,
      compositeScore: comp,
      volatilityCluster: t.vol,
      divergenceSpread: t.div,
      forwardVolRatio: t.fwd,
      dataAsOf: t.asof,
    };
  });
  lb["quant/config/global/universeSize"] = scored.length;
  await db.ref().update(lb);

  const mine = scored.findIndex((t) => t.s === symbol);
  return {
    volatilityCluster: vol,
    divergenceSpread: divergence,
    compositeScore: mine >= 0 ? zdiv[mine] + zvol[mine] : 0,
    universeSize: scored.length,
  };
}
