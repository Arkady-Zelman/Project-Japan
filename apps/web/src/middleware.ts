/**
 * Dual-auth middleware (BUILD_SPEC §6).
 *
 *  - Anonymous: /, /login, /(auth)/*, /dashboard, read-only data routes,
 *    Next internals, static assets.
 *  - Authenticated: /workbench, /lab, /api/value-asset, /api/run-backtest.
 *
 * Unauthenticated requests to gated pages 302 → /login?next=... .
 * Unauthenticated POSTs to gated APIs return 401.
 *
 * Session cookie is read + refreshed via @supabase/ssr on every request.
 */

import { NextResponse, type NextRequest } from "next/server";

import { updateSession } from "@/lib/supabase/middleware";

const ANON_PATHS = new Set(["/", "/dashboard", "/login", "/workbench", "/lab"]);
const ANON_PATH_PREFIXES = ["/auth/", "/login/", "/api/forecast-paths", "/api/regime-states", "/api/stack-curve", "/api/regional-balance", "/api/stack-curve/latest", "/api/bos-strategy", "/api/demo-valuation", "/api/demo-backtest"];
const PROTECTED_PAGE_PREFIXES: string[] = [];
const PROTECTED_API_PREFIXES = ["/api/value-asset", "/api/run-backtest", "/api/assets"];

function isAnon(pathname: string) {
  if (ANON_PATHS.has(pathname)) return true;
  return ANON_PATH_PREFIXES.some((p) => pathname.startsWith(p));
}

export async function middleware(request: NextRequest) {
  const { response, user } = await updateSession(request);
  const { pathname, search } = request.nextUrl;

  if (user || isAnon(pathname)) {
    return response;
  }

  if (PROTECTED_API_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  if (PROTECTED_PAGE_PREFIXES.some((p) => pathname.startsWith(p))) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(loginUrl);
  }

  return response;
}

export const config = {
  matcher: [
    // Match everything except: _next/static, _next/image, favicon, common static assets.
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|woff|woff2|ttf)$).*)",
  ],
};
