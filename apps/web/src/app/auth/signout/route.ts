/**
 * /auth/signout — clears the Supabase session cookie and redirects to /.
 */

import { NextResponse } from "next/server";

import { createSessionClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const supabase = createSessionClient();
  await supabase.auth.signOut();
  const url = new URL(request.url);
  return NextResponse.redirect(new URL("/dashboard", url.origin), { status: 303 });
}
