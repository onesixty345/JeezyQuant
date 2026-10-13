# JeezyQuant — a report card for stocks 📊

**What is this?** A website that watches stocks and gives each one a score,
like a report card. High scores mean the stock looks strong. Low scores mean
it looks weak. That's it. No trading, no buying, no selling — just scores
to help with research.

**Live site:** https://jeezy-quant.vercel.app

## What does it do?

Every weekday, a robot wakes up, looks at the stock market, does some math,
and updates a leaderboard:

- 🐂 **Top 10 Bullish** — the stocks with the best scores
- 🐻 **Top 10 Bearish** — the stocks with the worst scores

If the data is more than a day old, the site shows a **STALE** banner so you
know the scores might be out of date.

You can also type in any stock ticker (like `MU` or `NVDA`) and hit
**Add Ticker** — the site fetches its history and scores it right away.
You don't have to wait for the robot.

## How does it work? (the simple version)

Think of it like grading a student's report card. For each stock, the robot
checks three subjects and combines them into one final grade:

1. **Jumpiness** — Has the stock's price been calm or all over the place?
   Stocks tend to go through jumpy periods and calm periods, like weather.
2. **Story check** — Does the company's money story match its stock price?
   If a company's sales are growing but its stock is falling (or the other
   way around), something interesting is happening.
3. **AI forecast** — A Google AI model called TimesFM looks at the price
   history and guesses how bouncy the next 30 days might be.

Each stock gets a grade in each subject. Then all the grades are compared
across every stock being tracked, and each stock gets one final **score**.
The leaderboard is just the stocks sorted by that score.

## Where does the data come from?

- **Stock prices:** a free service called FMP (250 free lookups per day —
  the robot is careful never to go over). If FMP doesn't cover a stock,
  the robot automatically tries **yfinance** instead, which is also free.
- **Company sales:** quarterly revenue numbers, so the robot can do the
  "story check."
- **Saved homework:** every price the robot ever downloads gets saved in
  a database (Firebase). It never downloads the same day twice.

## What does it cost to run?

**$0.** The website runs on Vercel's free plan. The robot runs on Modal's
free CPU plan. The data comes from free tiers. The database is an existing
Firebase project. The whole thing is designed to never spend a cent.

## For builders (the slightly less simple part)

```
web/     → the website (Next.js + Tailwind, deployed on Vercel)
modal/   → the robot (Python on Modal)
  quant_job.py        → daily cron + scoring math + leaderboard refresh
  fmp_adapter.py      → talks to FMP (free tier, 250 calls/day budget)
  yfinance_adapter.py → backup data source when FMP doesn't cover a symbol
  hybrid_adapter.py   → tries FMP first, falls back to yfinance automatically
  timesfm_forecast.py → Google TimesFM volatility forecast (CPU)
docs/    → database layout, security rules, cache design
```

- Robot schedule: Monday–Friday, 21:30 UTC, on Modal (`quant-dashboard` app).
- Secrets (API keys, Firebase credentials) live in Modal Secrets and Vercel
  env vars — never in this repo, ever.
- Every robot run writes an audit log, so you can always see what it did.

## Important honesty notes

- This is a **research tool**, not financial advice. Scores are math, not
  recommendations.
- With only a couple of stocks tracked, the scores mostly just rank them
  against each other. The more stocks on the leaderboard, the more the
  scores mean.
- Past price patterns don't predict the future. The AI forecast is a guess
  with math behind it — still a guess.
