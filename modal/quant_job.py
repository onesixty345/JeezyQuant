"""
Quant Dashboard — Modal backend stub (Phase 1, RTDB edition).

Two entry points:
  1. daily_quant_run  — cron Mon–Fri 21:30 UTC (after US market close), T4 GPU.
  2. backfill_ticker  — secured web endpoint, called by the Next.js UI when a
                        user adds a ticker. One-time historical pull only.

Writes go to the existing Realtime Database under /quant/ via the Admin SDK.

Secrets (Modal Secrets manager, name: "quant-dashboard-secrets"):
  - DATA_API_KEY               # FMP or Alpaca key — NEVER in the repo
  - FIREBASE_SERVICE_ACCOUNT   # JSON string of the least-privilege service account
  - FIREBASE_DATABASE_URL      # e.g. https://jeezyplayground-default-rtdb.firebaseio.com
  - BACKFILL_SECRET            # shared secret the Next.js API route must send

Phase 1 note: provider fetch + TimesFM wiring are interfaces with explicit
TODOs. No API calls are executed until the append-only cache logic is approved.
"""

import os
import time
import uuid
from datetime import datetime, timezone

import modal

# ----------------------------------------------------------------------------
# App / image / secrets
# ----------------------------------------------------------------------------

app = modal.App("quant-dashboard")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
)

secrets = [modal.Secret.from_name("quant-dashboard-secrets")]

DATA_PROVIDER = os.environ.get("DATA_PROVIDER", "fmp")  # "fmp" | "alpaca"
DAILY_LIMIT = 250
SAFETY_RESERVE = 10
TIMESFM_MODEL_ID = "google/timesfm-3.0-pytorch"  # TODO Phase 2: verify exact HF repo id


# ----------------------------------------------------------------------------
# RTDB helpers (Admin SDK — bypasses security rules; least-privilege SA)
# ----------------------------------------------------------------------------

_db_root = None

def get_root():
    """Returns the /quant DatabaseReference, initializing the Admin SDK once."""
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


# ----------------------------------------------------------------------------
# Rate-limit budget (transactional)
# ----------------------------------------------------------------------------

def check_budget(root) -> int:
    """Resets the daily counter if needed; returns usable calls after reserve."""
    cfg_ref = root.child("config/global")

    def _reset_txn(current):
        if not current or current.get("lastResetDate") != utc_today():
            current = current or {}
            current["apiCallsUsedToday"] = 0
            current["lastResetDate"] = utc_today()
        return current

    cfg_ref.transaction(_reset_txn)
    cfg = cfg_ref.get() or {}
    usable = DAILY_LIMIT - int(cfg.get("apiCallsUsedToday", 0)) - SAFETY_RESERVE
    return max(usable, 0)


def spend(root, n: int):
    from firebase_admin import db as rtdb
    root.child("config/global/apiCallsUsedToday").transaction(
        lambda v: (v or 0) + n
    )


# ----------------------------------------------------------------------------
# Data provider interface (Phase 2 implements per provider)
# ----------------------------------------------------------------------------

class MarketDataProvider:
    """Interface. FMP and Alpaca adapters implement these; each returns
    (payload, calls_consumed)."""

    def daily_bars(self, symbol: str, days: int):
        raise NotImplementedError  # TODO Phase 2

    def historical_bars(self, symbol: str, years: int = 2):
        raise NotImplementedError  # TODO Phase 2

    def quarterly_revenue(self, symbol: str):
        raise NotImplementedError  # TODO Phase 2

    def company_profile(self, symbol: str):
        raise NotImplementedError  # TODO Phase 2

    def upstream_suppliers(self, symbol: str, top_n: int = 2):
        raise NotImplementedError  # TODO Phase 2


# ----------------------------------------------------------------------------
# ML inference (TimesFM)
# ----------------------------------------------------------------------------

_model = None

def load_timesfm():
    """Lazy-load TimesFM once per container. Returns (model, checkpoint_sha)."""
    global _model
    if _model is None:
        # TODO Phase 2: verify TIMESFM_MODEL_ID on Hugging Face first —
        # google/timesfm-3.0-pytorch must resolve to a real repo + revision.
        # from huggingface_hub import snapshot_download
        # ckpt = snapshot_download(repo_id=TIMESFM_MODEL_ID)
        # ... load per the repo's documented PyTorch API ...
        raise RuntimeError("TimesFM wiring is Phase 2 (model id unverified)")
    return _model


def compute_factors(price_points, supplier_histories, revenue_quarters):
    """Returns raw factor dict. No hardcoded weights — see docs/rtdb-schema.md.

    price_points:        sorted list of (date_str, close)
    supplier_histories:  { sup_symbol: [(date_str, close), ...] }
    revenue_quarters:    sorted list of (period, revenue)

    volatilityCluster: 63-day rolling realized-vol percentile vs 2-yr history.
    divergenceSpread:  stock 90d return minus supplier YoY revenue growth.
    compositeScore:    z(divergence) + z(volatility) across universe —
                       computed in the cron after all tickers are scored.
    """
    # TODO Phase 2: TimesFM forecast -> volatility clustering signal;
    #               numpy/pandas for the realized-vol + divergence math.
    raise NotImplementedError("Factor computation is Phase 2")


# ----------------------------------------------------------------------------
# Entry point 1: one-time backfill (secured web endpoint)
# ----------------------------------------------------------------------------

@app.function(image=image, secrets=secrets, timeout=600)
@modal.fastapi_endpoint(method="POST")
def backfill_ticker(payload: dict):
    # The Next.js route must send:  x-backfill-secret: <BACKFILL_SECRET>
    # TODO Phase 2: verify header, run the ≤6-call historical pull, write
    # date-keyed children under /quant/tickers/{SYMBOL}, set meta/status="active".
    return {"status": "stub", "note": "Phase 2 implements the backfill flow"}


# ----------------------------------------------------------------------------
# Entry point 2: daily cron
# ----------------------------------------------------------------------------

@app.function(
    image=image,
    gpu="T4",
    secrets=secrets,
    schedule=modal.Cron("30 21 * * 1-5"),  # 21:30 UTC, Mon–Fri
    timeout=3600,
)
def daily_quant_run():
    run_id = str(uuid.uuid4())
    started_ms = now_ms()
    root = get_root()
    log = {
        "runId": run_id,
        "trigger": "cron",
        "startedAt": started_ms,
        "modelCheckpoint": "n/a",
        "tickersProcessed": 0,
        "tickersFailed": [],
        "apiCallsUsed": 0,
        "errors": [],
    }

    try:
        usable = check_budget(root)
        # TODO Phase 2:
        #  1. read /quant/tickers, filter meta/status == "active",
        #     oldest meta/lastUpdated first
        #  2. per ticker: 1 call daily delta (last 5d); write only dates >
        #     meta/dataAsOf to priceHistory/{YYYY-MM-DD}; spend budget
        #  3. load_timesfm() once; compute_factors per ticker
        #  4. z-score composite across universe; write factors + push factorHistory
        #  5. refresh /quant/leaderboard/{SYMBOL} (denormalized UI node)
        #  6. update config/global/lastSuccessfulRun
        #  7. stop cleanly at budget floor -> status "partial", budgetExhausted=true
        log["status"] = "stub"
        log["usableBudget"] = usable
    except Exception as e:  # never fail silently — always log
        log["status"] = "failed"
        log["errors"].append({"ticker": None, "stage": "run", "message": str(e)})
    finally:
        finished_ms = now_ms()
        log["finishedAt"] = finished_ms
        log["durationSec"] = (finished_ms - started_ms) / 1000
        root.child("system_logs").push(log)

    return {"runId": run_id, "status": log["status"]}
