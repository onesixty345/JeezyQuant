import { NextResponse } from "next/server";

// POST /api/tickers { symbol: "MU" }
// 1. Validates the symbol.
// 2. Creates /quant/tickers/{SYMBOL}/meta with status "backfill_queued"
//    via the Admin SDK (server-side service account — never exposed).
// 3. Triggers the secured Modal backfill endpoint (x-backfill-secret header).
//
// No market-data API calls happen here — the Modal backend owns all provider calls.

const DATABASE_URL = process.env.FIREBASE_DATABASE_URL;
const MODAL_BACKFILL_URL = process.env.MODAL_BACKFILL_URL;
const BACKFILL_SECRET = process.env.MODAL_BACKFILL_SECRET;

export async function POST(req: Request) {
  try {
    const { symbol } = await req.json();
    const clean = typeof symbol === "string" ? symbol.trim().toUpperCase() : "";
    if (!/^[A-Z.]{1,10}$/.test(clean)) {
      return NextResponse.json({ error: "Invalid ticker symbol." }, { status: 400 });
    }
    if (!DATABASE_URL || !MODAL_BACKFILL_URL || !BACKFILL_SECRET) {
      return NextResponse.json(
        { error: "Backend not configured (missing env vars)." },
        { status: 503 }
      );
    }

    // TODO Phase 2: Admin SDK write to /quant/tickers/{clean}/meta, then POST
    // to MODAL_BACKFILL_URL with the x-backfill-secret header.
    // Phase 1: acknowledge the contract without executing anything.
    return NextResponse.json({
      symbol: clean,
      status: "backfill_queued (stub — Phase 2 wires RTDB + Modal)",
    });
  } catch {
    return NextResponse.json({ error: "Bad request." }, { status: 400 });
  }
}
