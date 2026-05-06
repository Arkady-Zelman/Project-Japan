/**
 * Browser-side Supabase client.
 *
 * Uses the publishable / anon key and respects RLS. Currently used by the
 * dashboard's Realtime subscription on `compute_runs` to live-update the
 * ingest-status table without a page reload.
 */

"use client";

import { createClient } from "@supabase/supabase-js";

import type { Database } from "@jepx/shared-types";

let _client: ReturnType<typeof createClient<Database>> | null = null;

export function createBrowserClient() {
  if (_client) return _client;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set."
    );
  }
  _client = createClient<Database>(url, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  return _client;
}
