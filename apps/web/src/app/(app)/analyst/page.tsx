/**
 * /analyst — M9 AI Analyst (chat + scratchpad).
 *
 * Server Component: fetches the dev user's existing chat sessions and hands
 * them to the AnalystClient which manages selection, send, and Realtime
 * subscription.
 */

import { createServerClient } from "@/lib/supabase/server";
import { AnalystClient, type ChatSessionRow } from "@/components/analyst/AnalystClient";

export const dynamic = "force-dynamic";

const DEV_USER_ID = process.env.JEPX_DEV_USER_ID;

async function fetchSessions(): Promise<ChatSessionRow[]> {
  if (!DEV_USER_ID) return [];
  const supabase = createServerClient();
  const { data } = await supabase
    .from("chat_sessions")
    .select("id, title, created_at")
    .eq("user_id", DEV_USER_ID)
    .order("created_at", { ascending: false })
    .limit(50);
  return (data ?? []) as ChatSessionRow[];
}

export default async function AnalystPage() {
  const sessions = await fetchSessions();
  return (
    <main className="mx-auto max-w-7xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-3xl font-semibold tracking-tight">AI Analyst</h1>
        <p className="mt-2 text-sm text-neutral-500">
          Chat-style assistant with read-only SQL, charting, correlations,
          quick models, and what-if BESS valuations.
        </p>
      </header>
      <AnalystClient initialSessions={sessions} />
    </main>
  );
}
