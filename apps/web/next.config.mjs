import { config } from "dotenv";
import path from "node:path";
import { fileURLToPath } from "node:url";

// The repo's .env.local lives at the repo root (per CLAUDE.md convention),
// not inside apps/web. Hook into Next.js's env-loading by populating
// process.env from the root file before the config object is read.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
config({ path: path.resolve(__dirname, "../../.env.local") });

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow imports from the workspace root (so `@jepx/shared-types` resolves
  // through the linked workspace package).
  transpilePackages: ["@jepx/shared-types"],
};

export default nextConfig;
