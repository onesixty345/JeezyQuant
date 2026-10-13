"""Hybrid market-data adapter: FMP first, yfinance on entitlement gating.

FMP's free tier entitles only a small server-side symbol whitelist; other
symbols 402 with "not available under your current subscription"
(FMPSymbolNotEntitled — permanent for the symbol, e.g. MU Oct 2026).
This adapter absorbs that case per-method by falling back to yfinance,
which is free/keyless and covers essentially all listed symbols.

Design notes:
  - Same read interface as FMPAdapter (daily_bars, historical_bars,
    quarterly_revenue, company_profile).
  - `calls` counts FMP calls only (the billable ones). `drain_fmp_calls()`
    returns and resets the count so call sites can spend() exactly what
    FMP consumed — yfinance never touches the 250/day budget.
  - Fallback applies ONLY to entitlement gating. FMPQuotaExhausted (daily
    budget hit) is never papered over: silently switching sources mid-run
    would mix data vendors inside one scoring pass.
  - `fallback_symbols` records which symbols were served by yfinance, so
    the job can tag meta/dataSource for the UI.
"""

from fmp_adapter import (
    FMPAdapter,
    FMPError,
    FMPQuotaExhausted,
    FMPSymbolNotEntitled,
)
from yfinance_adapter import YFinanceAdapter


class HybridDataAdapter:
    def __init__(self, api_key=None):
        self.fmp = FMPAdapter(api_key)
        self.yf = YFinanceAdapter()
        self.fallback_symbols = set()

    @property
    def calls(self) -> int:
        """Billable FMP calls so far (yfinance excluded).

        Note the failed FMP attempt that triggers a fallback still counts:
        _get() increments before the 402 check, so the 250/day budget
        stays exact with no call-site changes.
        """
        return self.fmp.calls

    # -- internals ---------------------------------------------------------
    def _run(self, symbol: str, method: str, *args):
        try:
            return getattr(self.fmp, method)(*args)
        except FMPSymbolNotEntitled:
            self.fallback_symbols.add(symbol)
            return getattr(self.yf, method)(*args)

    # -- interface (mirrors FMPAdapter) ------------------------------------
    def daily_bars(self, symbol, from_date, to_date):
        return self._run(symbol, "daily_bars", symbol, from_date, to_date)

    def historical_bars(self, symbol, from_date, to_date):
        return self._run(symbol, "historical_bars", symbol, from_date, to_date)

    def quarterly_revenue(self, symbol, limit=5):
        return self._run(symbol, "quarterly_revenue", symbol, limit)

    def company_profile(self, symbol):
        return self._run(symbol, "company_profile", symbol)


__all__ = [
    "HybridDataAdapter",
    "FMPAdapter",
    "FMPError",
    "FMPQuotaExhausted",
    "FMPSymbolNotEntitled",
]
