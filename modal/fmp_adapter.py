"""FMP (Financial Modeling Prep) stable-API adapter.

Every method returns (payload, calls_consumed). HTTP 402 (FMP's quota /
restricted responses, plain-text body) raises FMPQuotaExhausted so the cron
can stop cleanly instead of crashing.

Verified endpoints (stable base, key as ?apikey=):
  - /historical-price-eod/full?symbol=&from=&to=   -> flat array of daily bars
  - /income-statement?symbol=&period=quarter&limit=  -> quarterly financials
      (free plan: limit<=5, i.e. 5 quarters ~ 15 months; limit>5 -> 402)
  - /profile?symbol=                              -> company info
There is no supply-chain endpoint on the free tier: upstream_suppliers()
returns [] by design; supplier identity comes from the manual override.
"""

import os

import requests

BASE = "https://financialmodelingprep.com/stable"


class FMPQuotaExhausted(Exception):
    """402 from FMP: daily quota hit."""


class FMPSymbolNotEntitled(Exception):
    """402 from FMP: this symbol is not covered by the plan (permanent for
    the symbol — e.g. MU on the free tier, Oct 2026). Not a quota issue."""


class FMPError(Exception):
    """Any other non-200 from FMP."""


class FMPAdapter:
    def __init__(self, api_key: str | None = None):
        self.key = api_key or os.environ["DATA_API_KEY"]
        self.calls = 0

    # -- plumbing ---------------------------------------------------------
    def _get(self, path: str, params: dict):
        params = {**params, "apikey": self.key}
        r = requests.get(BASE + path, params=params, timeout=30)
        self.calls += 1
        if r.status_code == 402:
            body = r.text or ""
            # Distinguish quota exhaustion from per-symbol entitlement:
            # "not available under your current subscription" is permanent
            # for that symbol and must NOT stall the whole cron.
            if "not available under your current subscription" in body:
                raise FMPSymbolNotEntitled(f"{path}: {body[:200]}")
            raise FMPQuotaExhausted(f"{path}: {body[:200]}")
        if r.status_code != 200:
            raise FMPError(f"{path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    # -- interface ---------------------------------------------------------
    def daily_bars(self, symbol: str, from_date: str, to_date: str):
        """1 call. Returns [{date, close, volume}] oldest -> newest."""
        data = self._get(
            "/historical-price-eod/full",
            {"symbol": symbol, "from": from_date, "to": to_date},
        )
        bars = [
            {"date": b["date"], "close": b["close"], "volume": b.get("volume", 0)}
            for b in data
            if b.get("date") and b.get("close") is not None
        ]
        return sorted(bars, key=lambda b: b["date"])

    def historical_bars(self, symbol: str, from_date: str, to_date: str):
        """1 call. Same endpoint; the date range does the work."""
        return self.daily_bars(symbol, from_date, to_date)

    def quarterly_revenue(self, symbol: str, limit: int = 5):
        """1 call. Free plan caps at 5 quarters (~15 months) — enough for one
        YoY comparison (latest quarter vs same quarter last year).
        Returns [{period: 'YYYY-QN', revenue, reportedDate}] newest -> oldest."""
        data = self._get(
            "/income-statement",
            {"symbol": symbol, "period": "quarter", "limit": min(limit, 5)},
        )
        out = []
        for row in data:
            if row.get("revenue") is None:
                continue
            out.append(
                {
                    "period": f"{row.get('fiscalYear')}-{row.get('period')}",
                    "revenue": row["revenue"],
                    "reportedDate": row.get("date"),
                }
            )
        return out

    def company_profile(self, symbol: str):
        """1 call. Returns {companyName, exchange}."""
        data = self._get("/profile", {"symbol": symbol})
        row = data[0] if data else {}
        return {
            "companyName": row.get("companyName") or symbol,
            "exchange": row.get("exchange") or "",
        }

    def upstream_suppliers(self, symbol: str, top_n: int = 2):
        """0 calls. FMP's free tier has no supply-chain endpoint, so this is
        intentionally honest: supplier identity comes from the manual override
        (backfill payload 'suppliers' or a later admin update), never invented."""
        return []
