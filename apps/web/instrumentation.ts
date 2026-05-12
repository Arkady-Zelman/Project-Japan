/**
 * Next.js instrumentation hook — initializes Sentry per runtime.
 * Runs once per server start; no-op if SENTRY_DSN is not set.
 */

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("./sentry.edge.config");
  }
}

export { captureRequestError as onRequestError } from "@sentry/nextjs";
