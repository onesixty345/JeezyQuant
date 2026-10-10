import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // No secrets here. Server routes read process.env at runtime (Vercel env vars).
  // firebase-admin must stay external: Vercel's file tracer (nft) misses files
  // it loads dynamically, which crashes the serverless function on startup.
  serverExternalPackages: ["firebase-admin"],
};

export default nextConfig;
