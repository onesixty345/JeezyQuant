import { NextResponse } from "next/server";
import { adminDb, adminAuth, isAllowlisted } from "@/lib/admin";

// POST /api/tickers { symbol: "MU" } + Authorization: Bearer <Firebase ID token>
// 1. Verifies the caller's Firebase ID token and allowlist membership.
// 2. Validates the symbol; skips if already active/queued (idempotent).
// 3. Writes /quant/tickers/{SYMBOL}/meta status "backfill_queued" via Admin SDK.
// 4. Triggers the secured Modal backfill endpoint (x-backfill-secret header).
//
// No market-data API calls happen here — the Modal backend owns all provider calls.

const MODAL_BACKFILL_URL = process.env.MODAL_BACKFILL_URL;
const BACKFILL_SECRET = process.env.MODAL_BACKFILL_SECRET;

export async function POST(req: Request) {
  try {
    // --- 1. Caller auth ---
    const m = (req.headers.get("authorization") ?? "").match(/^Bearer (.+)$/);
    if (!m) {
      return NextResponse.json({ error: "Not signed in." }, { status: 401 });
    }
    let email: string | undefined;
    try {
      const decoded = await (await adminAuth()).verifyIdToken(m[1]);
      email = decoded.email;
    } catch {
      return NextResponse.json(
        { error: "Invalid session. Sign in again." },
        { status: 401 }
      );
    }
    if (!isAllowlisted(email)) {
      return NextResponse.json({ error: "Not authorized." }, { status: 403 });
    }

    // --- 2. Validate ---
    const { symbol } = await req.json();
    const clean = typeof symbol === "string" ? symbol.trim().toUpperCase() : "";
    if (!/^[A-Z.]{1,10}$/.test(clean)) {
      return NextResponse.json({ error: "Invalid ticker symbol." }, { status: 400 });
    }
    if (!MODAL_BACKFILL_URL || !BACKFILL_SECRET) {
      return NextResponse.json(
        { error: "Backend not configured (missing env vars)." },
        { status: 503 }
      );
    }

    const db = await adminDb();
    const metaRef = db.ref(`quant/tickers/${clean}/meta`);
    const existingStatus = ((await metaRef.get()).val() as { status?: string } | null)
      ?.status;
    if (existingStatus === "active" || existingStatus === "backfill_queued") {
      return NextResponse.json({ symbol: clean, status: existingStatus });
    }

    // --- 3. Queue ---
    await metaRef.set({
      symbol: clean,
      status: "backfill_queued",
      queuedAt: Date.now(),
      queuedBy: email,
    });

    // --- 4. Trigger Modal backfill ---
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 55000);
    try {
      const r = await fetch(MODAL_BACKFILL_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-backfill-secret": BACKFILL_SECRET,
        },
        body: JSON.stringify({
          symbol: clean,
          secret: BACKFILL_SECRET,
          suppliers: [],
        }),
        signal: controller.signal,
      });
      const data = (await r.json()) as {
        status?: string;
        bars?: number;
        calls?: number;
        reason?: string;
      };
      if (data?.status === "ok") {
        return NextResponse.json({
          symbol: clean,
          status: "active",
          bars: data.bars,
          calls: data.calls,
        });
      }
      await metaRef.update({
        status: "backfill_failed",
        error: String(data?.reason ?? "unknown").slice(0, 300),
      });
      return NextResponse.json(
        { symbol: clean, status: "backfill_failed", reason: data?.reason },
        { status: 502 }
      );
    } catch (e) {
      // Timeout / network error: backfill may still be running server-side.
      const note = e instanceof Error ? e.message : "request failed";
      await metaRef.update({
        status: "backfill_queued",
        note: note.slice(0, 200),
      });
      return NextResponse.json(
        {
          symbol: clean,
          status: "backfill_queued",
          note: "Still running — refresh shortly.",
        },
        { status: 202 }
      );
    } finally {
      clearTimeout(timeout);
    }
  } catch {
    return NextResponse.json({ error: "Bad request." }, { status: 400 });
  }
}
