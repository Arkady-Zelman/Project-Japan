/**
 * /auth/callback — exchanges the magic-link OTP code for a session cookie,
 * then redirects to `next` (defaults to /workbench).
 */

import { NextResponse } from "next/server";

import { createSessionClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const next = url.searchParams.get("next") ?? "/workbench";

  if (!code) {
    return NextResponse.redirect(new URL("/login?error=missing_code", url.origin));
  }

  const supabase = createSessionClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) {
    const failUrl = new URL("/login", url.origin);
    failUrl.searchParams.set("error", error.message);
    return NextResponse.redirect(failUrl);
  }

  return NextResponse.redirect(new URL(next, url.origin));
}
