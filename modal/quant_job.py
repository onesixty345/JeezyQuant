"""
Quant Dashboard — Modal backend (Phase 2, RTDB + FMP + TimesFM 3.0).

Two entry points:
  1. daily_quant_run  — cron Mon–Fri 21:30 UTC (after US market close), CPU.
  2. backfill_ticker  — secured web endpoint, called by the Next.js UI when a
                        user adds a ticker. One-time historical pull only.

Writes go to the existing Realtime Database under /quant/ via the Admin SDK.

Secrets (Modal Secrets manager, name: "quant-dashboard-secrets"):
  - DATA_API_KEY               # FMP key — NEVER in the repo
  - FIREBASE_SERVICE_ACCOUNT   # JSON string of the least-privilege service account
  - FIREBASE_DATABASE_URL      # https://jeezyplayground-default-rtdb.firebaseio.com
  - BACKFILL_SECRET            # shared secret the Next.js API route must send

Factor definitions (no hardcoded weights):
  - volatilityCluster: 63-day rolling realized-vol percentile vs 2-yr history
    (numpy, deterministic). 0..1; high = clustered/risky regime.
  - divergenceSpread: stock 90d return minus supplier YoY revenue growth
    (mean of suppliers with quarterly data; falls back to the company's own
    revenue YoY when no supplier fundamentals exist — documented, not silent).
  - forwardVolRatio: TimesFM 30d forecast dispersion / trailing dispersion.
  - compositeScore: z(divergenceSpread) + z(volatilityCluster) across the
    universe scored in the run. Transparent, equal-weight, documented.
"""

import hmac
import os
import re
import time
import uuid
from datetime import datetime, timezone, timedelta

import modal
from fastapi import Request
from pydantic import BaseModel

# Local helper modules (fmp_adapter.py, timesfm_forecast.py) are baked into the
# image via add_local_dir — Modal does not auto-package sibling imports on
# deploy. The code lands at /root/quant_code, so it must be on sys.path
# before those imports run.
import sys as _sys

if "/root/quant_code" not in _sys.path:
    _sys.path.insert(0, "/root/quant_code")

from fmp_adapter import FMPAdapter, FMPQuotaExhausted, FMPSymbolNotEntitled, FMPError
from hybrid_adapter import HybridDataAdapter
from timesfm_forecast import (
    forward_vol_ratio,
    TimesFMUnavailable,
    MODEL_ID as TIMESFM_MODEL_ID,
)

# ----------------------------------------------------------------------------
# App / image / secrets
# ----------------------------------------------------------------------------

app = modal.App("quant-dashboard")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
)

import pathlib

_LOCAL_DIR = pathlib.Path(__file__).resolve().parent

app = modal.App("quant-dashboard")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
    # Bake the helper modules (fmp_adapter.py, timesfm_forecast.py) into the
    # image — Modal does not auto-package sibling imports on deploy.
    # copy=True (not the default mount) so redeploys deterministically pick
    # up code changes; otherwise warm containers can serve stale code.
    .add_local_dir(str(_LOCAL_DIR), remote_path="/root/quant_code", copy=True)
)

secrets = [modal.Secret.from_name("quant-dashboard-secrets")]

DAILY_LIMIT = 250
SAFETY_RESERVE = 10
BACKFILL_BUDGET = 8  # profile + history + revenue + 2x(sup history + sup revenue) + margin
MAX_FAILURES = 3
REVENUE_REFRESH_DAYS = 30  # fundamentals move quarterly; refresh at most monthly


# ----------------------------------------------------------------------------
# RTDB helpers (Admin SDK — bypasses security rules; least-privilege SA)
# ----------------------------------------------------------------------------

_db_root = None


def get_root():
    global _db_root
    if _db_root is None:
        import json

        import firebase_admin
        from firebase_admin import credentials, db as rtdb

        cred = credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"]))
        firebase_admin.initialize_app(
            cred, {"databaseURL": os.environ["FIREBASE_DATABASE_URL"]}
        )
        _db_root = rtdb.reference("/quant")
    return _db_root


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def now_ms() -> int:
    return int(time.time() * 1000)


def check_budget(root) -> int:
    """Resets the daily counter if needed; returns usable calls after reserve."""
    cfg_ref = root.child("config/global")

    def _reset(current):
        current = current or {}
        if current.get("lastResetDate") != utc_today():
            current["apiCallsUsedToday"] = 0
            current["lastResetDate"] = utc_today()
        return current

    cfg_ref.transaction(_reset)
    cfg = cfg_ref.get() or {}
    return max(DAILY_LIMIT - int(cfg.get("apiCallsUsedToday", 0)) - SAFETY_RESERVE, 0)


def spend(root, n: int):
    root.child("config/global/apiCallsUsedToday").transaction(lambda v: (v or 0) + n)


# ----------------------------------------------------------------------------
# Factor math (numpy; deterministic; no tuned weights)
# ----------------------------------------------------------------------------

def realized_vol_percentile(closes):
    """63-day rolling std of log returns, percentile-ranked vs full history.
    Returns 0..1. <126 points of history -> 0.5 (neutral, documented)."""
    import numpy as np

    c = np.asarray(closes, dtype=float)
    if len(c) < 126:
        return 0.5
    lr = np.diff(np.log(c))
    roll = np.array([lr[i - 63 : i].std() for i in range(63, len(lr) + 1)])
    return float((roll < roll[-1]).mean())


def trailing_return(closes, days=90):
    if len(closes) < 2:
        return 0.0
    n = min(days + 1, len(closes))
    return float(closes[-1] / closes[-n] - 1.0)


def yoy_growth(quarters):
    """Newest quarter revenue vs same quarter last year. quarters: newest-first
    [{revenue}]. Needs >=5 quarters (the free-tier cap) -> None otherwise."""
    if len(quarters) < 5:
        return None
    newest, year_ago = quarters[0]["revenue"], quarters[4]["revenue"]
    if not newest or not year_ago:
        return None
    return float(newest / year_ago - 1.0)


def zscores(values):
    import numpy as np

    v = np.asarray(values, dtype=float)
    mu, sd = v.mean(), v.std()
    if sd < 1e-12:
        return [0.0] * len(v)
    return ((v - mu) / sd).tolist()


def _sorted_quarters(rev_map):
    """rev_map: {period: {revenue, reportedDate}} -> newest-first list."""
    return sorted(
        [{"period": p, **v} for p, v in rev_map.items()],
        key=lambda q: q["period"],
        reverse=True,
    )


# ----------------------------------------------------------------------------
# Entry point 1: one-time backfill (secured web endpoint)
# ----------------------------------------------------------------------------


class BackfillPayload(BaseModel):
    symbol: str
    secret: str = ""  # fallback if the header can't be read
    suppliers: list[str] = []  # manual override: top upstream supplier symbols


@app.function(image=image, secrets=secrets, timeout=900)
@modal.fastapi_endpoint(method="POST")
async def backfill_ticker(payload: BackfillPayload, request: Request):
    started = now_ms()
    run_id = str(uuid.uuid4())
    log = {
        "runId": run_id,
        "trigger": "backfill",
        "startedAt": started,
        "modelCheckpoint": "n/a",
        "tickersProcessed": 0,
        "tickersFailed": [],
        "apiCallsUsed": 0,
        "errors": [],
    }
    root = get_root()
    try:
        provided = request.headers.get("x-backfill-secret") or payload.secret
        expected = os.environ.get("BACKFILL_SECRET", "")
        if not expected or not hmac.compare_digest(provided, expected):
            return {"status": "unauthorized"}

        symbol = payload.symbol.strip().upper()
        if not re.fullmatch(r"[A-Z.]{1,10}", symbol):
            return {"status": "error", "reason": "invalid symbol"}

        if check_budget(root) < BACKFILL_BUDGET:
            return {"status": "deferred",
                    "reason": "daily budget too low, retry tomorrow"}

        fmp = HybridDataAdapter()
        to_date = utc_today()
        from_date = (datetime.now(timezone.utc) - timedelta(days=730)).strftime("%Y-%m-%d")

        profile = fmp.company_profile(symbol)          # 1
        bars = fmp.historical_bars(symbol, from_date, to_date)  # 1
        revenue = fmp.quarterly_revenue(symbol)        # 1
        if not bars:
            raise FMPError(f"no price history returned for {symbol}")

        suppliers = [s.strip().upper() for s in payload.suppliers[:2] if s.strip()]
        sup_data = {}
        for sup in suppliers:
            try:
                sup_bars = fmp.historical_bars(sup, from_date, to_date)  # 1
                sup_rev = fmp.quarterly_revenue(sup)                    # 1
                sup_data[sup] = (sup_bars, sup_rev)
            except (FMPError, FMPQuotaExhausted) as e:
                log["errors"].append({"ticker": sup, "stage": "backfill",
                                      "message": str(e)[:200]})

        # date-keyed writes: idempotent, a retried backfill overwrites
        updates = {
            f"tickers/{symbol}/meta": {
                "companyName": profile["companyName"],
                "exchange": profile["exchange"],
                "status": "active",
                "dataSource": ("yfinance" if symbol in fmp.fallback_symbols
                               else "fmp"),
                "addedAt": started,
                "lastUpdated": started,
                "dataAsOf": bars[-1]["date"],
                "revenueAsOf": started,
                "consecutiveFailures": 0,
            }
        }
        for b in bars:
            updates[f"tickers/{symbol}/priceHistory/{b['date']}"] = {
                "close": b["close"], "volume": b["volume"]}
        for q in revenue:
            updates[f"tickers/{symbol}/revenueQuarterly/{q['period']}"] = {
                "revenue": q["revenue"], "reportedDate": q["reportedDate"]}
        for sup, (sup_bars, sup_rev) in sup_data.items():
            for b in sup_bars:
                updates[f"tickers/{symbol}/suppliers/{sup}/priceHistory/{b['date']}"] = {
                    "close": b["close"]}
            for q in sup_rev:
                updates[f"tickers/{symbol}/suppliers/{sup}/revenueQuarterly/{q['period']}"] = {
                    "revenue": q["revenue"], "reportedDate": q["reportedDate"]}
        root.update(updates)

        spend(root, fmp.calls)
        log["apiCallsUsed"] = fmp.calls
        log["tickersProcessed"] = 1
        log["status"] = "ok"
        return {"status": "ok", "symbol": symbol, "calls": fmp.calls,
                "bars": len(bars), "suppliers": list(sup_data)}
    except FMPSymbolNotEntitled as e:
        # Permanent for this symbol on the current plan (e.g. MU on free).
        # Mark it so the cron skips it without burning budget or failing.
        try:
            root.update({f"tickers/{payload.symbol.strip().upper()}/meta/status":
                         "unsupported"})
        except Exception:
            pass
        log["status"] = "unsupported"
        log["errors"].append({"ticker": payload.symbol, "stage": "backfill",
                              "message": f"not entitled: {str(e)[:200]}"})
        return {"status": "unsupported",
                "reason": "symbol not covered by the FMP plan"}
    except FMPQuotaExhausted as e:
        log["status"] = "partial"
        log["errors"].append({"ticker": payload.symbol, "stage": "backfill",
                              "message": f"quota: {str(e)[:200]}"})
        return {"status": "deferred", "reason": "FMP quota exhausted"}
    except Exception as e:
        log["status"] = "failed"
        log["errors"].append({"ticker": payload.symbol, "stage": "backfill",
                              "message": str(e)[:300]})
        return {"status": "error", "reason": str(e)[:200]}
    finally:
        finished = now_ms()
        log["finishedAt"] = finished
        log["durationSec"] = (finished - started) / 1000
        try:
            root.child("system_logs").push(log)
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Entry point 1b: score a single ticker on demand (no FMP calls)
# ----------------------------------------------------------------------------
# Called right after a backfill so a newly added ticker gets factors and
# joins the leaderboard immediately, using its as-of cached data. The daily
# cron still refreshes everything when new market data is available.
# Recomputes z-scores across the full universe so existing tickers' composite
# scores update too.


class ScorePayload(BaseModel):
    symbol: str
    secret: str


@app.function(image=image, secrets=secrets, timeout=900)
@modal.fastapi_endpoint(method="POST")
async def score_ticker(payload: ScorePayload, request: Request):
    started = now_ms()
    run_id = str(uuid.uuid4())
    log = {
        "runId": run_id,
        "trigger": "score_on_add",
        "startedAt": started,
        "modelCheckpoint": TIMESFM_MODEL_ID,
        "tickersProcessed": 0,
        "tickersFailed": [],
        "apiCallsUsed": 0,
        "errors": [],
    }
    root = get_root()
    try:
        provided = request.headers.get("x-backfill-secret") or payload.secret
        expected = os.environ.get("BACKFILL_SECRET", "")
        if not expected or not hmac.compare_digest(provided, expected):
            return {"status": "unauthorized"}

        symbol = payload.symbol.strip().upper()
        if not re.fullmatch(r"[A-Z.]{1,10}", symbol):
            return {"status": "error", "reason": "invalid symbol"}

        node = root.child(f"tickers/{symbol}").get() or {}
        meta = node.get("meta", {})
        if meta.get("status") != "active":
            return {"status": "error",
                    "reason": f"ticker not active (status={meta.get('status')})"}

        # --- factor math on cached history (zero FMP calls) ---
        hist = node.get("priceHistory", {})
        dates = sorted(hist)
        closes = [hist[d]["close"] for d in dates]
        if len(closes) < 60:
            return {"status": "error",
                    "reason": "insufficient cached price history"}

        rev_map = dict(node.get("revenueQuarterly", {}))
        sup_nodes = node.get("suppliers", {})

        vol = realized_vol_percentile(closes)
        ret90 = trailing_return(closes, 90)

        sup_yoys = []
        sup_maps = {}
        for sup in list(sup_nodes.keys())[:2]:
            sq = _sorted_quarters(sup_nodes.get(sup, {}).get("revenueQuarterly", {}))
            g = yoy_growth(sq)
            if g is not None:
                sup_yoys.append(g)
            existing = sup_nodes.get(sup, {}).get("priceHistory", {})
            sup_maps[sup] = {d: v["close"] if isinstance(v, dict) else v
                             for d, v in existing.items()}
        own_yoy = yoy_growth(_sorted_quarters(rev_map))
        div_base = (sum(sup_yoys) / len(sup_yoys)) if sup_yoys else own_yoy
        divergence = ret90 - (div_base if div_base is not None else 0.0)

        try:
            rev_yoy_map = {d: own_yoy for d in dates} if own_yoy is not None else {}
            fwd = forward_vol_ratio(dates, closes, sup_maps, rev_yoy_map)
        except TimesFMUnavailable as e:
            fwd = None
            log["errors"].append({"ticker": symbol, "stage": "timesfm",
                                "message": str(e)[:200]})

        root.update({
            f"tickers/{symbol}/meta/lastUpdated": now_ms(),
            f"tickers/{symbol}/meta/consecutiveFailures": 0,
            f"tickers/{symbol}/factors": {
                "computedAt": now_ms(),
                "modelCheckpoint": TIMESFM_MODEL_ID,
                "horizonDays": 30,
                "volatilityCluster": vol,
                "divergenceSpread": divergence,
                "forwardVolRatio": fwd,
            },
        })
        log["tickersProcessed"] += 1

        # --- z-score composite across the full universe ---
        tickers = root.child("tickers").get() or {}
        scored = []
        for s, d in tickers.items():
            if not isinstance(d, dict):
                continue
            f = d.get("factors") or {}
            if f.get("volatilityCluster") is None or f.get("divergenceSpread") is None:
                continue
            m = d.get("meta", {})
            scored.append((s, m.get("companyName", s),
                           f["divergenceSpread"], f["volatilityCluster"],
                           f.get("forwardVolRatio"), m.get("dataAsOf")))
        if scored:
            zdiv = zscores([d for _, _, d, _, _, _ in scored])
            zvol = zscores([v for _, _, _, v, _, _ in scored])
            lb = {}
            for (s, company, _d, vol_, fwd_, asof), zd, zv in zip(scored, zdiv, zvol):
                comp = zd + zv
                div = next(d for x, _, d, _, _, _ in scored if x == s)
                lb[f"tickers/{s}/factors/compositeScore"] = comp
                lb[f"tickers/{s}/factorHistory/{run_id}_{s}"] = {
                    "computedAt": now_ms(),
                    "modelCheckpoint": TIMESFM_MODEL_ID,
                    "volatilityCluster": vol_,
                    "divergenceSpread": div,
                    "forwardVolRatio": fwd_,
                    "compositeScore": comp,
                }
                lb[f"leaderboard/{s}"] = {
                    "symbol": s,
                    "companyName": company,
                    "compositeScore": comp,
                    "volatilityCluster": vol_,
                    "divergenceSpread": div,
                    "forwardVolRatio": fwd_,
                    "dataAsOf": asof,
                }
            root.update(lb)
            root.child("config/global/universeSize").set(len(scored))

        log["status"] = "ok"
        return {"status": "ok", "symbol": symbol,
                "volatilityCluster": vol, "divergenceSpread": divergence,
                "forwardVolRatio": fwd,
                "universeSize": len(scored)}
    except Exception as e:
        log["status"] = "failed"
        log["errors"].append({"ticker": payload.symbol, "stage": "score",
                            "message": str(e)[:300]})
        return {"status": "error", "reason": str(e)[:200]}
    finally:
        finished = now_ms()
        log["finishedAt"] = finished
        log["durationSec"] = (finished - started) / 1000
        try:
            root.child("system_logs").push(log)
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Entry point 2: daily cron
# ----------------------------------------------------------------------------


@app.function(
    image=image,
    # CPU (not GPU): Modal requires a payment method on file for any GPU.
    # TimesFM 3.0 (200M params) runs in <60s/ticker on CPU — fine for a
    # watchlist-sized universe inside the 3600s timeout. Revisit GPU past
    # ~50 tickers.
    secrets=secrets,
    schedule=modal.Cron("30 21 * * 1-5"),  # 21:30 UTC, Mon–Fri
    timeout=3600,
)
def daily_quant_run():
    run_id = str(uuid.uuid4())
    started = now_ms()
    root = get_root()
    log = {
        "runId": run_id,
        "trigger": "cron",
        "startedAt": started,
        "modelCheckpoint": TIMESFM_MODEL_ID,
        "tickersProcessed": 0,
        "tickersFailed": [],
        "apiCallsUsed": 0,
        "errors": [],
    }
    fmp = HybridDataAdapter()
    status = "ok"
    budget_hit = False

    try:
        usable = check_budget(root)
        tickers = root.child("tickers").get() or {}
        active = [s for s, d in tickers.items()
                  if isinstance(d, dict) and d.get("meta", {}).get("status") == "active"]
        active.sort(key=lambda s: tickers[s].get("meta", {}).get("lastUpdated", 0))
        to_date = utc_today()

        scored = []  # (symbol, company, div, vol, fwd, dataAsOf) for z-scoring

        for symbol in active:
            if usable < 3:  # price + up to 2 supplier deltas
                budget_hit = True
                break
            node = tickers.get(symbol, {})
            meta = node.get("meta", {})
            try:
                data_as_of = meta.get("dataAsOf", "2000-01-01")
                from_date = (datetime.strptime(data_as_of, "%Y-%m-%d")
                             + timedelta(days=1)).strftime("%Y-%m-%d")

                # --- price delta (1 call; skipped when already current) ---
                new_bars = []
                if from_date <= to_date:
                    bars = fmp.daily_bars(symbol, from_date, to_date)
                    new_bars = [b for b in bars if b["date"] > data_as_of]
                    spend(root, 1); usable -= 1
                price_updates = {}
                for b in new_bars:
                    price_updates[f"tickers/{symbol}/priceHistory/{b['date']}"] = {
                        "close": b["close"], "volume": b["volume"]}
                if new_bars:
                    price_updates[f"tickers/{symbol}/meta/dataAsOf"] = new_bars[-1]["date"]
                if price_updates:
                    root.update(price_updates)

                # --- fundamentals refresh at most monthly ---
                rev_map = dict(node.get("revenueQuarterly", {}))
                sup_nodes = node.get("suppliers", {})
                if now_ms() - int(meta.get("revenueAsOf", 0)) > REVENUE_REFRESH_DAYS * 86400000:
                    need = 1 + min(len(sup_nodes), 2)
                    if usable < need:
                        budget_hit = True
                        break
                    rev_updates = {}
                    for q in fmp.quarterly_revenue(symbol):
                        rev_updates[f"tickers/{symbol}/revenueQuarterly/{q['period']}"] = {
                            "revenue": q["revenue"], "reportedDate": q["reportedDate"]}
                        rev_map[q["period"]] = {"revenue": q["revenue"],
                                                "reportedDate": q["reportedDate"]}
                    spend(root, 1); usable -= 1
                    for sup in list(sup_nodes.keys())[:2]:
                        for q in fmp.quarterly_revenue(sup):
                            rev_updates[f"tickers/{symbol}/suppliers/{sup}/revenueQuarterly/{q['period']}"] = {
                                "revenue": q["revenue"], "reportedDate": q["reportedDate"]}
                        spend(root, 1); usable -= 1
                    rev_updates[f"tickers/{symbol}/meta/revenueAsOf"] = now_ms()
                    root.update(rev_updates)
                    # re-read supplier nodes to include fresh revenue
                    sup_nodes = root.child(f"tickers/{symbol}/suppliers").get() or sup_nodes

                # --- supplier price deltas (1 call each) ---
                sup_maps = {}
                for sup in list(sup_nodes.keys())[:2]:
                    if usable < 1:
                        budget_hit = True
                        break
                    existing = sup_nodes.get(sup, {}).get("priceHistory", {})
                    if from_date <= to_date:
                        sup_bars = fmp.daily_bars(sup, from_date, to_date)
                        sup_up = {}
                        for b in sup_bars:
                            if b["date"] > data_as_of:
                                sup_up[f"tickers/{symbol}/suppliers/{sup}/priceHistory/{b['date']}"] = {
                                    "close": b["close"]}
                        if sup_up:
                            root.update(sup_up)
                        spend(root, 1); usable -= 1
                        for b in sup_bars:
                            existing[b["date"]] = b["close"]
                    sup_maps[sup] = {d: v["close"] if isinstance(v, dict) else v
                                     for d, v in existing.items()}
                if budget_hit:
                    break

                # --- factor math on merged history ---
                hist = node.get("priceHistory", {})
                for b in new_bars:
                    hist[b["date"]] = {"close": b["close"], "volume": b["volume"]}
                dates = sorted(hist)
                closes = [hist[d]["close"] for d in dates]

                vol = realized_vol_percentile(closes)
                ret90 = trailing_return(closes, 90)

                sup_yoys = []
                for sup in list(sup_nodes.keys())[:2]:
                    sq = _sorted_quarters(sup_nodes.get(sup, {}).get("revenueQuarterly", {}))
                    g = yoy_growth(sq)
                    if g is not None:
                        sup_yoys.append(g)
                own_yoy = yoy_growth(_sorted_quarters(rev_map))
                div_base = (sum(sup_yoys) / len(sup_yoys)) if sup_yoys else own_yoy
                divergence = ret90 - (div_base if div_base is not None else 0.0)

                try:
                    rev_yoy_map = {d: own_yoy for d in dates} if own_yoy is not None else {}
                    fwd = forward_vol_ratio(dates, closes, sup_maps, rev_yoy_map)
                except TimesFMUnavailable as e:
                    fwd = None
                    log["errors"].append({"ticker": symbol, "stage": "timesfm",
                                          "message": str(e)[:200]})

                scored.append((symbol, meta.get("companyName", symbol),
                               divergence, vol, fwd, meta.get("dataAsOf")))
                root.update({
                    f"tickers/{symbol}/meta/lastUpdated": now_ms(),
                    f"tickers/{symbol}/meta/consecutiveFailures": 0,
                    f"tickers/{symbol}/factors": {
                        "computedAt": now_ms(),
                        "modelCheckpoint": TIMESFM_MODEL_ID,
                        "horizonDays": 30,
                        "volatilityCluster": vol,
                        "divergenceSpread": divergence,
                        "forwardVolRatio": fwd,
                    },
                })
                log["tickersProcessed"] += 1

            except FMPSymbolNotEntitled as e:
                # Permanent for this symbol on the current plan: quarantine it
                # so it never burns budget or fails the run again.
                root.update({f"tickers/{symbol}/meta/status": "unsupported"})
                log["errors"].append({"ticker": symbol, "stage": "delta",
                                      "message": f"not entitled: {str(e)[:200]}"})
                continue
            except FMPQuotaExhausted as e:
                log["errors"].append({"ticker": symbol, "stage": "delta",
                                      "message": f"quota: {str(e)[:200]}"})
                budget_hit = True
                break
            except (FMPError, Exception) as e:
                fails = int(meta.get("consecutiveFailures", 0)) + 1
                patch = {f"tickers/{symbol}/meta/consecutiveFailures": fails}
                if fails >= MAX_FAILURES:
                    patch[f"tickers/{symbol}/meta/status"] = "error"
                root.update(patch)
                log["tickersFailed"].append(symbol)
                log["errors"].append({"ticker": symbol, "stage": "delta",
                                      "message": str(e)[:300]})
                continue

        # --- z-score composite across the run's universe (documented, equal-weight) ---
        if scored:
            zdiv = zscores([d for _, _, d, _, _, _ in scored])
            zvol = zscores([v for _, _, _, v, _, _ in scored])
            lb = {}
            for (symbol, company, _d, vol, fwd, asof), zd, zv in zip(scored, zdiv, zvol):
                comp = zd + zv
                div = next(d for s, _, d, _, _, _ in scored if s == symbol)
                lb[f"tickers/{symbol}/factors/compositeScore"] = comp
                lb[f"tickers/{symbol}/factorHistory/{run_id}_{symbol}"] = {
                    "computedAt": now_ms(),
                    "modelCheckpoint": TIMESFM_MODEL_ID,
                    "volatilityCluster": vol,
                    "divergenceSpread": div,
                    "forwardVolRatio": fwd,
                    "compositeScore": comp,
                }
                lb[f"leaderboard/{symbol}"] = {
                    "symbol": symbol,
                    "companyName": company,
                    "compositeScore": comp,
                    "volatilityCluster": vol,
                    "divergenceSpread": div,
                    "forwardVolRatio": fwd,
                    "dataAsOf": asof,
                }
            root.update(lb)
            root.child("config/global/universeSize").set(len(scored))

        log["apiCallsUsed"] = fmp.calls
        if budget_hit:
            status = "partial"
            log["budgetExhausted"] = True
        else:
            root.child("config/global/lastSuccessfulRun").set(now_ms())
        log["status"] = status

    except Exception as e:  # never fail silently
        log["status"] = "failed"
        log["errors"].append({"ticker": None, "stage": "run", "message": str(e)[:300]})
    finally:
        finished = now_ms()
        log["finishedAt"] = finished
        log["durationSec"] = (finished - started) / 1000
        try:
            get_root().child("system_logs").push(log)
        except Exception:
            pass

    return {"runId": run_id, "status": log["status"],
            "processed": log["tickersProcessed"]}
