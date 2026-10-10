# Quant Dashboard — serverless quantitative stock screening

Zero-cost stack: **Next.js (Vercel)** + **Firebase Realtime Database** (existing
`jeezyplayground` project, namespaced under `/quant/`) + **Modal (T4 cron)** +
**FMP/Alpaca free tier** + **TimesFM** via Hugging Face.

> **Phase 1 status: scaffolding only.** No API calls, no deploys, no secrets —
> the append-only cache logic in `docs/append-only-cache.md` needs approval first.

## Layout

| Path | What |
|---|---|
| `docs/rtdb-schema.md` | Exact RTDB tree (date-keyed history, denormalized leaderboard node) |
| `docs/rtdb-rules.json` | Security rules to paste into the Firebase console |
| `docs/append-only-cache.md` | **Cache logic for approval** — backfill vs daily delta, 250/day budget |
| `modal/quant_job.py` | Modal stub: cron entrypoint, secured backfill endpoint, audit logging |
| `modal/requirements.txt` | Python deps (`firebase-admin`, `torch`, `transformers`, …) |
| `web/` | Next.js dashboard: Top 10 Bullish/Bearish, add-ticker, STALE banner |

## Design notes (RTDB edition)

- History is stored in **date-keyed children** (`priceHistory/{YYYY-MM-DD}`),
  making appends idempotent — a retried day overwrites instead of duplicating.
- The UI reads only the tiny denormalized `/quant/leaderboard` node the backend
  refreshes each run; 2-year histories never cross the wire to the browser.
- Security rules: public read on tickers/leaderboard/config, zero client writes,
  `system_logs` fully locked. The Admin SDK bypasses rules for the backend.

## What I verified in this environment (Phase 1)

- Node 24, npm 10, Python 3.12 — present.
- Modal CLI **not** installed; no Modal token — needed in Phase 2.
- GitHub App cannot create repos — Raim created `JeezyQuant`; code is pushed here.

## Blockers that need Raim (Phase 2)

1. **Data provider** — choose **FMP vs Alpaca**; provide the API key via Secure Vault → I inject it into Modal Secrets (never in the repo).
2. **TimesFM checkpoint** — verify `google/timesfm-3.0-pytorch` resolves on Hugging Face before first inference run.
3. **Modal account** — `modal setup` needs an interactive token.
4. **Vercel project** — create in the dashboard (API creation is blocked on this account), connect this repo, set env vars from `web/.env.example`.
5. **Firebase IAM** — mint a dedicated service account with minimal RTDB access for the Modal backend.
6. **RTDB rules** — paste `docs/rtdb-rules.json` into Console → Realtime Database → Rules.

## Security rules (non-negotiable)

- No API keys, service-account JSON, or secrets in the repo — ever.
- Provider key + Firebase credentials live in **Modal Secrets** (`quant-dashboard-secrets`).
- Vercel gets only `NEXT_PUBLIC_*` client config + server env vars; nothing secret is bundled client-side.
- Every backend run writes to `/quant/system_logs` (checkpoint, quota, duration, failures). Silent skips are not allowed.
