/**
 * Server-side Supabase client.
 *
 * Used by Server Components and Route Handlers. Reads service-role key from
 * env so this client bypasses RLS — never expose it to the browser.
 *
 * The browser counterpart at `client.ts` uses the anon key and is RLS-bound.
 */

import { createClient } from "@supabase/supabase-js";

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
  });
}
