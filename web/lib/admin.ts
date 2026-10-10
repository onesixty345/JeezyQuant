// Firebase Admin SDK — server-only. Never import from client components.
// Lazy init so `next build` doesn't crash when env vars are absent.
import { initializeApp, getApps, cert, type App } from "firebase-admin/app";
import { getDatabase, type Database } from "firebase-admin/database";
import { getAuth, type Auth } from "firebase-admin/auth";

let _app: App | null = null;

export function adminApp(): App {
  if (_app) return _app;
  const saJson = process.env.FIREBASE_SERVICE_ACCOUNT_JSON;
  if (!saJson) throw new Error("Missing FIREBASE_SERVICE_ACCOUNT_JSON env var");
  const dbUrl = process.env.FIREBASE_DATABASE_URL;
  if (!dbUrl) throw new Error("Missing FIREBASE_DATABASE_URL env var");
  _app = getApps().length
    ? getApps()[0]!
    : initializeApp({ credential: cert(JSON.parse(saJson)), databaseURL: dbUrl });
  return _app;
}

export function adminDb(): Database {
  return getDatabase(adminApp());
}

export function adminAuth(): Auth {
  return getAuth(adminApp());
}

const ALLOWLIST = (
  process.env.AUTHORIZED_EMAILS ??
  process.env.NEXT_PUBLIC_AUTHORIZED_EMAILS ??
  "onesixty345@gmail.com"
)
  .split(",")
  .map((e) => e.trim().toLowerCase())
  .filter(Boolean);

export function isAllowlisted(email: string | undefined): boolean {
  return !!email && ALLOWLIST.includes(email.toLowerCase());
}
