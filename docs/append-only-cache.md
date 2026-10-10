# Append-Only Cache Logic (RTDB) — FOR APPROVAL

> **No API calls are executed until this logic is approved.** Phase 1 is scaffolding only.

## Goal
Protect the strict **250 requests/day** data-provider limit by never re-downloading
history. The daily cron fetches only the newest delta and writes it to
date-keyed children.

## Write paths

### Path A — New ticker (one-time backfill, user-triggered)
1. User submits a symbol in the Next.js UI → `POST /api/tickers`.
2. API route validates the symbol, creates `/quant/tickers/{SYMBOL}/meta` with
   `status="backfill_queued"` via the Admin SDK, then calls the **secured Modal
   backfill endpoint** (`POST /backfill`, header `x-backfill-secret`).
3. The backfill function makes the one-time historical pull:
   - ~3 calls: 2 yrs daily bars, quarterly financials (revenue), company profile.
   - ~2 calls: top-2 upstream supplier identification + their 2-yr daily bars.
   - **Budget: ≤ 6 calls per new ticker, once ever.**
4. Writes `priceHistory/{YYYY-MM-DD}`, `revenueQuarterly/{YYYY-QN}`, and
   `suppliers/{SUP}/priceHistory/{YYYY-MM-DD}`; sets `meta/status="active"`,
   `meta/dataAsOf=<latest date>`.
5. Any failure → `status="backfilling"`, error logged to `/quant/system_logs`;
   the UI shows "backfill pending" and the user can retry. Backfill writes are
   date-keyed, so a retried backfill overwrites rather than duplicates.

Supplier identification: provider's supply-chain / peers endpoint where available;
fallback is a manual `suppliersOverride` field Raim can set per ticker.
No invented supplier mappings — if the provider returns none, the ticker is
tracked with price+revenue only and flagged with an empty `suppliers` node.

### Path B — Daily cron (weekdays 21:30 UTC, T4 GPU)
1. Read `/quant/config/global`. If `lastResetDate` ≠ today (UTC), reset
   `apiCallsUsedToday=0` (transactional).
2. Compute remaining budget: `250 − apiCallsUsedToday`. Reserve **10 calls** as a
   safety buffer → usable = `remaining − 10`.
3. For each ticker with `meta/status="active"` (oldest `meta/lastUpdated` first):
   - Cost: **1 call** — fetch last 5 calendar days of daily bars (covers weekends/holidays).
   - Write only dates `> meta/dataAsOf` to `priceHistory/{YYYY-MM-DD}`.
     Existing dates are skipped, never re-fetched.
   - Revenue: quarterly — only re-fetch if `reportedDate` advanced (≤ 1 call, and
     only in earnings weeks; otherwise skipped).
   - Suppliers: same 1-call delta each (their bars are the covariate series).
   - **Steady-state cost: ~3 calls/ticker/day** → ~80 tickers fit the daily budget.
4. Run TimesFM inference per ticker (price = primary series; supplier bars +
   revenue growth = historical covariates). Write `factors` + push to
   `factorHistory/{pushId}`.
5. Refresh `/quant/leaderboard/{SYMBOL}` (the denormalized node the UI reads).
6. Update `/quant/config/global/lastSuccessfulRun`; push the run document to
   `/quant/system_logs` (checkpoint version, calls used, rate-limit remaining,
   duration, failures).
7. If budget hits the reserve floor mid-run: stop cleanly, log `status="partial"`
   with `budgetExhausted=true`, and resume the remaining tickers tomorrow.
   **Never silently skip** — every skip is a log entry.

## Failure & staleness contract
- Per-ticker exceptions are caught, counted in `meta/consecutiveFailures`, and logged.
  3 consecutive failures → `status="error"` (excluded from cron until manually re-queued).
- The UI banner rule: if `now − config/global/lastSuccessfulRun > 24h`, show
  **"STALE — backend has not completed a run in over 24 hours"**. A `partial` run
  still updates the timestamp (it completed honestly); a crashed run does not.

## What needs Raim's approval before Phase 2
- [ ] This append-only + budget-reserve logic
- [ ] Data provider choice: **FMP vs Alpaca** (free-tier shape differs; FMP has richer fundamentals)
- [ ] Supplier-identification fallback (manual override acceptable?)
- [ ] Composite score definition (`z(div) + z(vol)`, equal-weight, documented)
