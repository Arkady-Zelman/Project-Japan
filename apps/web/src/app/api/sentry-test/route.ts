/**
 * /api/_sentry-test — deliberate error endpoint for verifying Sentry wiring.
 * GET throws so the error lands in Sentry; POST checks status without throwing.
 * Disabled in production by checking NEXT_PUBLIC_SENTRY_DSN existence.
 */

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  throw new Error("Sentry test error — intentional, ignore");
}

export async function POST() {
  const enabled = Boolean(process.env.NEXT_PUBLIC_SENTRY_DSN);
  return NextResponse.json({ sentry_dsn_present: enabled });
}
