// Firebase Admin SDK — server-only. Never import from client components.
// Lazy init so `next build` doesn't crash when env vars are absent.
import admin from "firebase-admin";

let _app: admin.app.App | null = null;

export function adminApp(): admin.app.App {
  if (_app) return _app;
  const saJson = process.env.FIREBASE_SERVICE_ACCOUNT_JSON;
  if (!saJson) throw new Error("Missing FIREBASE_SERVICE_ACCOUNT_JSON env var");
  const dbUrl = process.env.FIREBASE_DATABASE_URL;
  if (!dbUrl) throw new Error("Missing FIREBASE_DATABASE_URL env var");
  _app = admin.apps.length
    ? (admin.apps[0] as admin.app.App)
    : admin.initializeApp({
        credential: admin.credential.cert(JSON.parse(saJson)),
        databaseURL: dbUrl,
      });
  return _app;
}

export function adminDb(): admin.database.Database {
  return admin.database(adminApp());
}

export function adminAuth(): admin.auth.Auth {
  return admin.auth(adminApp());
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
