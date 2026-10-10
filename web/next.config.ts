import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // No secrets here. Server routes read process.env at runtime (Vercel env vars).
};

export default nextConfig;
