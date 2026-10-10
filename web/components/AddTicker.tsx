"use client";

import { useState } from "react";

export default function AddTicker({ onAdded }: { onAdded: () => void }) {
  const [symbol, setSymbol] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const clean = symbol.trim().toUpperCase();
    if (!/^[A-Z.]{1,10}$/.test(clean)) {
      setMsg("Enter a valid ticker symbol (letters, up to 10 chars).");
      return;
    }
    setBusy(true);
    setMsg("");
    try {
      const res = await fetch("/api/tickers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: clean }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Request failed");
      setMsg(`${clean} queued — historical backfill started.`);
      setSymbol("");
      onAdded();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <input
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        placeholder="Add ticker (e.g. MU)"
        className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 font-mono uppercase placeholder:normal-case placeholder:text-zinc-500 focus:outline-none focus:border-zinc-500"
        maxLength={10}
      />
      <button
        type="submit"
        disabled={busy}
        className="rounded-md bg-zinc-100 px-4 py-2 text-sm font-semibold text-zinc-950 disabled:opacity-50"
      >
        {busy ? "Queueing…" : "Add ticker"}
      </button>
      {msg && <p className="text-sm text-zinc-400">{msg}</p>}
    </form>
  );
}
