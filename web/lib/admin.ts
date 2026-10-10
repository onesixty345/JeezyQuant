// Firebase Admin SDK — server-only. Never import from client components.
//
// NOTE: firebase-admin is loaded via dynamic import() inside the functions,
// not at module top-level. Vercel's file tracer (nft) can miss files that
// firebase-admin loads dynamically; a top-level static import crashes the
// whole serverless function (500 HTML) instead of a catchable error.
// Dynamic import keeps any load failure inside our try/catch as JSON.

type AdminModules = {
  app: typeof import("firebase-admin/app");
  database: typeof import("firebase-admin/database");
  auth: typeof import("firebase-admin/auth");
};

let _mods: AdminModules | null = null;
let _app: import("firebase-admin/app").App | null = null;

async function mods(): Promise<AdminModules> {
  if (!_mods) {
    const [app, database, auth] = await Promise.all([
      import("firebase-admin/app"),
      import("firebase-admin/database"),
      import("firebase-admin/auth"),
    ]);
    _mods = { app, database, auth };
  }
  return _mods;
}

export async function adminApp(): Promise<import("firebase-admin/app").App> {
  if (_app) return _app;
  const m = await mods();
  const saJson = process.env.FIREBASE_SERVICE_ACCOUNT_JSON;
  if (!saJson) throw new Error("Missing FIREBASE_SERVICE_ACCOUNT_JSON env var");
  const dbUrl = process.env.FIREBASE_DATABASE_URL;
  if (!dbUrl) throw new Error("Missing FIREBASE_DATABASE_URL env var");
  const apps = m.app.getApps();
  _app =
    apps.length > 0
      ? apps[0]!
      : m.app.initializeApp({
          credential: m.app.cert(JSON.parse(saJson)),
          databaseURL: dbUrl,
        });
  return _app;
}

export async function adminDb(): Promise<import("firebase-admin/database").Database> {
  const m = await mods();
  return m.database.getDatabase(await adminApp());
}

export async function adminAuth(): Promise<import("firebase-admin/auth").Auth> {
  const m = await mods();
  return m.auth.getAuth(await adminApp());
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
