import path from "node:path";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
// The admin bundle imports three shared customer components from ../cabinet/src.
// Build from the repository root so those files resolve, and pin React to the
// admin installation so the panel never ships two React copies. In the Docker
// image ../cabinet has no install of its own; the Dockerfile links
// ../cabinet/node_modules to this package's node_modules instead.
const repoRoot = path.resolve(here, "..");
// Turbopack resolves alias targets relative to its root, so point at ./admin/node_modules/...
const local = (name) => "./" + path.posix.join(path.relative(repoRoot, here).split(path.sep).join("/"), "node_modules", name);

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  distDir: "dist",
  trailingSlash: false,
  reactStrictMode: true,
  poweredByHeader: false,
  images: {unoptimized: true},
  env: {
    // Docker and Compose keep passing the historical VITE_API_URL build argument.
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? process.env.VITE_API_URL ?? "",
  },
  outputFileTracingRoot: repoRoot,
  turbopack: {
    root: repoRoot,
    resolveAlias: {
      react: local("react"),
      "react-dom": local("react-dom"),
    },
  },
};

export default nextConfig;
