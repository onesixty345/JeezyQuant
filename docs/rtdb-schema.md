# RTDB Schema — Quant Dashboard

Database: the existing Firebase **Realtime Database**
(`https://jeezyplayground-default-rtdb.firebaseio.com`, project `jeezyplayground`).
Everything lives under `/quant/` so it never collides with the CRUD API's paths.

All backend writes use the Firebase Admin SDK (bypasses security rules).
The Next.js UI reads via the client SDK; it never writes directly —
new tickers go through `POST /api/tickers` (server route, Admin SDK).

## Tree

```
/quant/
  tickers/{SYMBOL}/
    meta/
      companyName: string
      exchange: string
      status: "backfill_queued" | "backfilling" | "active" | "error"
      addedAt: number            # ServerValue.TIMESTAMP (ms epoch)
      lastUpdated: number        # last successful daily delta write
      dataAsOf: string           # "YYYY-MM-DD" of newest price point
      consecutiveFailures: number
    priceHistory/{YYYY-MM-DD}/
      close: number
      volume: number
    revenueQuarterly/{YYYY-QN}/  # e.g. "2026-Q3"
      revenue: number
      reportedDate: string       # "YYYY-MM-DD"
    suppliers/{SUP_SYMBOL}/
      meta/ { name: string }
      priceHistory/{YYYY-MM-DD}/ { close: number }
    factors/                     # latest raw ML outputs (overwritten each run)
      computedAt: number
      modelCheckpoint: string    # e.g. "google/timesfm-3.0-pytorch@sha256:…"
      horizonDays: number
      volatilityCluster: number  # 0–1, 63-day realized-vol percentile
      divergenceSpread: number   # stock 90d return − supplier revenue YoY
      compositeScore: number     # z(div) + z(vol), documented, not tuned
    factorHistory/{pushId}/
      { computedAt, modelCheckpoint, volatilityCluster, divergenceSpread, compositeScore }

  leaderboard/{SYMBOL}/          # denormalized by the backend each run — the ONLY
    symbol: string               # node the UI reads for the Top 10 views (tiny)
    companyName: string
    compositeScore: number
    volatilityCluster: number
    divergenceSpread: number
    dataAsOf: string

  system_logs/{pushId}/
    runId, trigger ("cron"|"backfill"), startedAt, finishedAt, durationSec,
    modelCheckpoint, tickersProcessed, tickersFailed[], apiCallsUsed,
    apiRateLimitRemaining, errors[{ ticker, stage, message }], status

  config/global/
    dataProvider: "fmp" | "alpaca"
    apiDailyLimit: 250
    apiCallsUsedToday: number
    lastResetDate: "YYYY-MM-DD"
    lastSuccessfulRun: number     # ms epoch — the UI stale banner reads this
    cronSchedule: "30 21 * * 1-5"
    staleThresholdHours: 24
    timesfmModelId: "google/timesfm-3.0-pytorch"
    universeSize: number
```

## Why date-keyed children (not arrays)

RTDB has no `arrayUnion`. Keying history by date (`priceHistory/{YYYY-MM-DD}`)
makes appends **idempotent by construction**: re-writing an existing date
overwrites it, so a retried or double-run day can never duplicate data.
Ordering is free via `orderByKey()`.

## Read-size discipline

RTDB returns whole nodes. The UI never reads `/quant/tickers/{SYMBOL}` directly
(it carries 2 years of history) — it reads the tiny `/quant/leaderboard` node
the backend refreshes each run. Detail views (Phase 3) can read a single ticker's
`meta` + `factors` children.

## Security rules

Paste `docs/rtdb-rules.json` into Console → Realtime Database → Rules.
Effect: public read on tickers/leaderboard/config; no client writes anywhere;
`system_logs` fully locked down. The Admin SDK bypasses rules, so the backend
is unaffected.
