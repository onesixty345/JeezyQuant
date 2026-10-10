"use client";

import { useEffect, useState, type ReactNode } from "react";
import {
  onAuthStateChanged,
  signInWithPopup,
  signOut,
  type User,
} from "firebase/auth";
import { getAuthClient, googleProvider } from "@/lib/firebase";

// Comma-separated allowlist; defaults to the owner's mailbox.
const AUTHORIZED_EMAILS = (process.env.NEXT_PUBLIC_AUTHORIZED_EMAILS ?? "onesixty345@gmail.com")
  .split(",")
  .map((e) => e.trim().toLowerCase())
  .filter(Boolean);

export default function AuthGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    return onAuthStateChanged(getAuthClient(), (u) => {
      setUser(u);
      setLoading(false);
    });
  }, []);

  async function handleSignIn() {
    setError("");
    try {
      await signInWithPopup(getAuthClient(), googleProvider);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    }
  }

  if (loading) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-16">
        <p className="text-sm text-zinc-500">Loading…</p>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-[70vh] max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
        <h1 className="text-2xl font-bold">Quant Dashboard</h1>
        <p className="text-sm text-zinc-500">
          Research screening only — sign in with Google to continue.
        </p>
        <button
          onClick={handleSignIn}
          className="rounded-md bg-zinc-100 px-5 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-white"
        >
          Sign in with Google
        </button>
        {error && <p className="text-sm text-red-400">{error}</p>}
      </main>
    );
  }

  const email = (user.email ?? "").toLowerCase();
  if (!AUTHORIZED_EMAILS.includes(email)) {
    return (
      <main className="mx-auto flex min-h-[70vh] max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
        <h1 className="text-2xl font-bold">Not authorized</h1>
        <p className="text-sm text-zinc-500">
          {user.email} isn&apos;t on the allowlist for this dashboard.
        </p>
        <button
          onClick={() => signOut(getAuthClient())}
          className="rounded-md border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:border-zinc-500"
        >
          Sign out
        </button>
      </main>
    );
  }

  return (
    <>
      <div className="border-b border-zinc-800">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-2">
          <span className="truncate text-xs text-zinc-500">{user.email}</span>
          <button
            onClick={() => signOut(getAuthClient())}
            className="text-xs text-zinc-500 hover:text-zinc-300"
          >
            Sign out
          </button>
        </div>
      </div>
      {children}
    </>
  );
}
