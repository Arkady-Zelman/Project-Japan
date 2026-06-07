/**
 * /api/sentry-test — deliberate error endpoint for verifying Sentry wiring.
 * GET throws so the error lands in Sentry; POST checks status without throwing.
 * GET is disabled in production so the deployed app cannot be used to flood
 * production Sentry.
 */

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  if (process.env.NODE_ENV === "production") {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  throw new Error("Sentry test error — intentional, ignore");
}

export async function POST() {
  const enabled = Boolean(process.env.NEXT_PUBLIC_SENTRY_DSN);
  return NextResponse.json({ sentry_dsn_present: enabled });
}
