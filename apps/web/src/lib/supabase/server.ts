/**
 * Server-side Supabase clients.
 *
 * Two flavors:
 *  - createServerClient: service-role (bypasses RLS). Reserved for admin reads:
 *    dashboard data spans, compute_runs aggregates, queueing rows on behalf of
 *    the authenticated user once their id is known.
 *  - createSessionClient: reads the session cookie via @supabase/ssr. RLS-bound.
 *    Use this when you need `auth.uid()` or need RLS enforced.
 *
 * Never expose either client to the browser; both read service-side env vars.
 */

import { createClient } from "@supabase/supabase-js";
import { createServerClient as createServerClientSSR, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";

import type { Database } from "@jepx/shared-types";

export function createServerClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !serviceKey) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set."
    );
  }
  return createClient<Database>(url, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
    global: {
      // Bypass Next 14's default `fetch` cache. Server Components/Route
      // Handlers default to caching every fetch keyed by URL+headers, which
      // makes Supabase reads return stale rows even with force-dynamic.
      fetch: (input, init) => fetch(input, { ...init, cache: "no-store" }),
    },
  });
}

export function createSessionClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set."
    );
  }
  const cookieStore = cookies();
  return createServerClientSSR<Database>(url, anonKey, {
    cookies: {
      get(name: string) {
        return cookieStore.get(name)?.value;
      },
      set(name: string, value: string, options: CookieOptions) {
        try {
          cookieStore.set({ name, value, ...options });
        } catch {
          // Server Components cannot set cookies; the middleware handles that.
        }
      },
      remove(name: string, options: CookieOptions) {
        try {
          cookieStore.set({ name, value: "", ...options });
        } catch {
          // Server Components cannot set cookies; the middleware handles that.
        }
      },
    },
  });
}
