/**
 * /api/agent — relay POST → Modal agent /chat as a streaming SSE response.
 *
 * Per BUILD_SPEC §6.6 + §9.1, this is a thin relay. It:
 *   1. zod-validates the request body
 *   2. attaches the dev-user id (M9.5 will substitute a real Supabase JWT)
 *   3. POSTs to MODAL_AGENT_ENDPOINT/chat
 *   4. pipes the upstream EventSource stream back to the browser unchanged
 *
 * No double-write to chat_messages here — the Modal agent already persists
 * messages + tool results + artifacts during the loop. The frontend then
 * subscribes via Realtime to render canonical state.
 */

import { NextResponse } from "next/server";
import { z } from "zod";

const MODAL_AGENT_ENDPOINT = process.env.MODAL_AGENT_ENDPOINT;
const DEV_USER_ID = process.env.JEPX_DEV_USER_ID;

const requestSchema = z.object({
  session_id: z.string().uuid().nullable().optional(),
  message: z.string().min(1).max(8_000),
});

export async function POST(request: Request) {
  if (!MODAL_AGENT_ENDPOINT) {
    return NextResponse.json(
      { error: "MODAL_AGENT_ENDPOINT not configured" },
      { status: 500 },
    );
  }
  if (!DEV_USER_ID) {
    return NextResponse.json(
      { error: "JEPX_DEV_USER_ID not configured" },
      { status: 500 },
    );
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  const parsed = requestSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  const { session_id, message } = parsed.data;

  // Forward to Modal. We pass session_id through so the Modal app reuses
  // the existing chat_sessions row; null/undefined means "create new".
  const upstream = await fetch(`${MODAL_AGENT_ENDPOINT}/chat`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-user-id": DEV_USER_ID,
      "accept": "text/event-stream",
    },
    body: JSON.stringify({ session_id: session_id ?? null, message }),
  });

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => upstream.statusText);
    return NextResponse.json(
      { error: `agent upstream ${upstream.status}: ${text.slice(0, 500)}` },
      { status: 502 },
    );
  }

  // Pipe the SSE stream back unchanged. Browser EventSource will see it.
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      "connection": "keep-alive",
    },
  });
}
