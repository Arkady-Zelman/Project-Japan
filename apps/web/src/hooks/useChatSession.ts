"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { createBrowserClient } from "@/lib/supabase/client";

/**
 * Subscribes to a single chat_sessions row + its chat_messages and
 * agent_artifacts. Provides `send(text)` which opens an SSE stream to
 * /api/agent and accumulates the in-flight assistant tokens until the
 * Realtime subscription delivers the canonical row.
 *
 * Per BUILD_SPEC §10 line 1132.
 */

export type ChatMessage = {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  tool_calls: ToolCallShape[] | null;
  tool_results: ToolResultShape[] | null;
  tokens_in: number | null;
  tokens_out: number | null;
  created_at: string;
};

export type ToolCallShape = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
};

export type ToolResultShape = {
  id: string;
  name: string;
  output: Record<string, unknown> | unknown[] | string | number | null;
};

export type AgentArtifact = {
  id: string;
  session_id: string;
  user_id: string;
  type: "chart" | "query_result" | "model_spec";
  title: string | null;
  spec_jsonb: Record<string, unknown>;
  created_at: string;
  expires_at: string | null;
  pinned: boolean | null;
};

export function useChatSession(sessionId: string | null): {
  messages: ChatMessage[];
  artifacts: AgentArtifact[];
  pending: boolean;
  inFlightAssistantText: string;
  inFlightToolCalls: ToolCallShape[];
  send: (text: string) => Promise<{ session_id: string } | null>;
} {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [artifacts, setArtifacts] = useState<AgentArtifact[]>([]);
  const [pending, setPending] = useState(false);
  const [inFlightAssistantText, setInFlightText] = useState("");
  const [inFlightToolCalls, setInFlightToolCalls] = useState<ToolCallShape[]>([]);
  const sessionIdRef = useRef<string | null>(sessionId);
  sessionIdRef.current = sessionId;

  // Fetch + subscribe whenever session changes.
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setArtifacts([]);
      return;
    }
    const supabase = createBrowserClient();
    const refetch = async () => {
      const [{ data: msgs }, { data: arts }] = await Promise.all([
        supabase
          .from("chat_messages")
          .select("*")
          .eq("session_id", sessionId)
          .order("created_at", { ascending: true }),
        supabase
          .from("agent_artifacts")
          .select("*")
          .eq("session_id", sessionId)
          .order("created_at", { ascending: false }),
      ]);
      setMessages((msgs ?? []) as ChatMessage[]);
      setArtifacts((arts ?? []) as AgentArtifact[]);
    };
    refetch();
    const ch = supabase
      .channel(`chat:${sessionId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "chat_messages", filter: `session_id=eq.${sessionId}` },
        () => { refetch(); },
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "agent_artifacts", filter: `session_id=eq.${sessionId}` },
        () => { refetch(); },
      )
      .subscribe();
    return () => {
      supabase.removeChannel(ch);
    };
  }, [sessionId]);

  const send = useCallback(
    async (text: string): Promise<{ session_id: string } | null> => {
      setPending(true);
      setInFlightText("");
      setInFlightToolCalls([]);
      try {
        const r = await fetch("/api/agent", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ session_id: sessionIdRef.current, message: text }),
        });
        if (!r.ok || !r.body) {
          const err = await r.text().catch(() => r.statusText);
          console.error("agent POST failed:", err);
          return null;
        }
        // Parse SSE stream chunk-by-chunk.
        const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
        let buf = "";
        let resolvedSessionId: string | null = null;
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += value;
          const events = buf.split("\n\n");
          buf = events.pop() ?? "";
          for (const evRaw of events) {
            const lines = evRaw.split("\n");
            let evType = "message";
            let dataStr = "";
            for (const ln of lines) {
              if (ln.startsWith("event:")) evType = ln.slice(6).trim();
              else if (ln.startsWith("data:")) dataStr += ln.slice(5).trim();
            }
            let data: Record<string, unknown> = {};
            try {
              data = dataStr ? JSON.parse(dataStr) : {};
            } catch {
              continue;
            }
            switch (evType) {
              case "session": {
                if (typeof data.session_id === "string") {
                  resolvedSessionId = data.session_id;
                }
                break;
              }
              case "token": {
                if (typeof data.text === "string") {
                  setInFlightText((prev) => prev + (data.text as string));
                }
                break;
              }
              case "tool_call": {
                setInFlightToolCalls((prev) => [
                  ...prev,
                  {
                    id: String(data.id),
                    name: String(data.name),
                    arguments: (data.arguments as Record<string, unknown>) ?? {},
                  },
                ]);
                break;
              }
              case "tool_result":
              case "artifact":
              case "message":
                // No-op locally; Realtime subscription delivers canonical state.
                break;
              case "error": {
                console.error("agent error:", data.message);
                break;
              }
              case "done":
                break;
            }
          }
        }
        return resolvedSessionId ? { session_id: resolvedSessionId } : null;
      } finally {
        setPending(false);
        setInFlightText("");
        setInFlightToolCalls([]);
      }
    },
    [],
  );

  return {
    messages,
    artifacts,
    pending,
    inFlightAssistantText,
    inFlightToolCalls,
    send,
  };
}
