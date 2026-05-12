import { config } from "dotenv";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { withSentryConfig } from "@sentry/nextjs";

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

// Sentry source-map upload runs on `next build` when SENTRY_AUTH_TOKEN is set.
// The wrapper is a no-op for `dev` and for builds without the auth token.
export default withSentryConfig(nextConfig, {
  silent: true,
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  widenClientFileUpload: true,
  hideSourceMaps: true,
  disableLogger: true,
});
