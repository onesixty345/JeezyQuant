// Firebase client SDK — reads only. All secrets stay server-side / in Modal.
//
// Initialization is lazy (via getters) so that `next build` prerendering and
// any server-side import don't crash when env vars are absent. The getters
// throw a clear error only when actually used without config.

import { initializeApp, getApps, type FirebaseApp } from "firebase/app";
import { getDatabase, type Database } from "firebase/database";
import { getAuth, GoogleAuthProvider, type Auth } from "firebase/auth";

function firebaseConfig() {
  return {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
    databaseURL: process.env.NEXT_PUBLIC_FIREBASE_DATABASE_URL,
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  };
}

let _app: FirebaseApp | null = null;
export function firebaseApp(): FirebaseApp {
  if (!_app) {
    _app = getApps().length ? getApps()[0]! : initializeApp(firebaseConfig());
  }
  return _app;
}

export function getRtdb(): Database {
  const dbUrl = process.env.NEXT_PUBLIC_FIREBASE_DATABASE_URL;
  if (!dbUrl) throw new Error("Missing NEXT_PUBLIC_FIREBASE_DATABASE_URL");
  return getDatabase(firebaseApp());
}

export function getAuthClient(): Auth {
  return getAuth(firebaseApp());
}

export const googleProvider = new GoogleAuthProvider();
