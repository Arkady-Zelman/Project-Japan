/**
 * Browser-side Supabase client, session-aware via `@supabase/ssr`.
 *
 * Reads the auth cookie set by the server during the magic-link callback, so
 * Realtime channels and RLS-bound queries authenticate as the signed-in user.
 * Anonymous users still get an anon-key client (Realtime channels on public
 * tables, like compute_runs, still work).
 */

"use client";

import { createBrowserClient as createBrowserClientSSR } from "@supabase/ssr";

import type { Database } from "@jepx/shared-types";

let _client: ReturnType<typeof createBrowserClientSSR<Database>> | null = null;

export function createBrowserClient() {
  if (_client) return _client;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set."
    );
  }
  _client = createBrowserClientSSR<Database>(url, anonKey);
  return _client;
}
