/** Customer cabinet and Telegram Mini App (same code, two build surfaces). */
const basePath = (process.env.NEXT_BASE_PATH || "").replace(/\/$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  distDir: "dist",
  basePath: basePath || undefined,
  trailingSlash: false,
  reactStrictMode: true,
  poweredByHeader: false,
  images: {unoptimized: true},
  env: {
    // Docker and Compose keep passing the historical VITE_* build arguments.
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? process.env.VITE_API_URL ?? "",
    NEXT_PUBLIC_SURFACE: process.env.NEXT_PUBLIC_SURFACE ?? process.env.VITE_SURFACE ?? "web",
    NEXT_PUBLIC_BASE_PATH: basePath,
  },
};

export default nextConfig;
