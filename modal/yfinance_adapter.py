"""yfinance fallback adapter — keyless price/fundamentals for symbols FMP gates.

FMP's free tier only entitles a small server-side symbol whitelist; anything
else 402s with "not available under your current subscription" (e.g. MU,
Oct 2026). yfinance (Yahoo Finance) is free, keyless, and covers essentially
all listed symbols, so it backs the methods the quant job needs most.

Interface mirrors FMPAdapter's read methods; every method returns the same
shapes. Failures raise FMPError (the job's generic provider-failure path)
so existing retry/quarantine handling applies unchanged.

Deliberate limits:
  - company_profile() does NOT call ticker.info (flaky/slow on recent
    yfinance); it returns the symbol itself. Names fill in when FMP
    entitles the symbol.
  - quarterly_revenue() maps statement columns to calendar quarters —
    an approximation, good enough for the YoY divergence factor.
"""

from datetime import datetime, timedelta

import yfinance as yf

from fmp_adapter import FMPError


def _yf_symbol(symbol: str) -> str:
    # yfinance uses dashes where FMP/exchanges use dots (BRK.B -> BRK-B).
    return symbol.replace(".", "-")


class YFinanceAdapter:
    def __init__(self):
        self.calls = 0  # yfinance calls are free; kept for interface parity

    # -- interface ---------------------------------------------------------
    def daily_bars(self, symbol: str, from_date: str, to_date: str):
        """Returns [{date, close, volume}] oldest -> newest (raw close)."""
        # yfinance `end` is exclusive: add a day to include to_date.
        end_excl = (datetime.strptime(to_date, "%Y-%m-%d")
                    + timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            df = yf.Ticker(_yf_symbol(symbol)).history(
                start=from_date, end=end_excl, auto_adjust=False)
        except Exception as e:
            raise FMPError(f"yfinance history failed for {symbol}: {e}") from e
        if df is None or df.empty:
            raise FMPError(f"no price history returned for {symbol}")
        bars = []
        for ts, row in df.iterrows():
            close = row.get("Close")
            if close is None or close != close:  # NaN check
                continue
            vol = row.get("Volume", 0)
            bars.append({
                "date": ts.strftime("%Y-%m-%d"),
                "close": float(close),
                "volume": int(vol) if vol == vol else 0,
            })
        if not bars:
            raise FMPError(f"no price history returned for {symbol}")
        return sorted(bars, key=lambda b: b["date"])

    def historical_bars(self, symbol: str, from_date: str, to_date: str):
        """Same endpoint; the date range does the work."""
        return self.daily_bars(symbol, from_date, to_date)

    def quarterly_revenue(self, symbol: str, limit: int = 5):
        """Best-effort quarterly revenue, newest -> oldest.

        Returns [{period: 'YYYY-QN', revenue, reportedDate}]. Periods are
        calendar-quarter approximations from statement column dates.
        Returns [] when Total Revenue is unavailable (factor degrades to
        price-only, same as an FMP-entitled symbol with no financials).
        """
        try:
            stmt = yf.Ticker(_yf_symbol(symbol)).quarterly_income_stmt
        except Exception:
            return []
        if stmt is None or stmt.empty:
            return []
        rev_row = None
        for label in ("Total Revenue", "TotalRevenue", "Revenue"):
            if label in stmt.index:
                rev_row = stmt.loc[label]
                break
        if rev_row is None:
            return []
        out = []
        for col in list(stmt.columns)[:limit]:
            try:
                ts = col if hasattr(col, "year") else datetime.strptime(
                    str(col)[:10], "%Y-%m-%d")
            except Exception:
                continue
            val = rev_row[col]
            if val is None or val != val:  # NaN check
                continue
            out.append({
                "period": f"{ts.year}-Q{(ts.month - 1) // 3 + 1}",
                "revenue": float(val),
                "reportedDate": ts.strftime("%Y-%m-%d"),
            })
        return out

    def company_profile(self, symbol: str):
        """No network call: yfinance .info is unreliable on recent versions."""
        return {"companyName": symbol, "exchange": ""}
