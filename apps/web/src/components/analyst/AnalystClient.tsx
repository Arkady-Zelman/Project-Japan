"use client";

import { useEffect, useState } from "react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useChatSession } from "@/hooks/useChatSession";

import { ChatInterface } from "./ChatInterface";
import { ScratchpadPane } from "./ScratchpadPane";

export type ChatSessionRow = {
  id: string;
  title: string | null;
  created_at: string;
};

type Props = {
  initialSessions: ChatSessionRow[];
};

export function AnalystClient({ initialSessions }: Props) {
  const [sessions, setSessions] = useState<ChatSessionRow[]>(initialSessions);
  const [sessionId, setSessionId] = useState<string | null>(
    initialSessions[0]?.id ?? null,
  );

  const {
    messages,
    artifacts,
    pending,
    inFlightAssistantText,
    inFlightToolCalls,
    send,
  } = useChatSession(sessionId);

  // After the first send into a freshly-created session, the API response
  // gives us back the new session_id; we slot that into local state and
  // refresh the sidebar.
  const handleSend = async (text: string) => {
    const result = await send(text);
    if (result?.session_id && result.session_id !== sessionId) {
      setSessionId(result.session_id);
      setSessions((prev) => {
        if (prev.find((s) => s.id === result.session_id)) return prev;
        return [
          { id: result.session_id, title: "New chat", created_at: new Date().toISOString() },
          ...prev,
        ];
      });
    }
  };

  // Keep sessions list fresh after the agent persists rows.
  useEffect(() => {
    if (!sessionId) return;
    if (!sessions.find((s) => s.id === sessionId)) {
      setSessions((prev) => [
        { id: sessionId, title: "New chat", created_at: new Date().toISOString() },
        ...prev,
      ]);
    }
  }, [sessionId, sessions]);

  return (
    <div className="grid h-[calc(100vh-180px)] grid-cols-1 gap-4 lg:grid-cols-[220px_1fr_1fr]">
      {/* Sessions sidebar */}
      <Card className="flex h-full flex-col">
        <CardHeader>
          <CardTitle>Sessions</CardTitle>
          <button
            type="button"
            className="mt-2 rounded-md border border-input bg-background px-3 py-1 text-xs"
            onClick={() => setSessionId(null)}
          >
            + New chat
          </button>
        </CardHeader>
        <CardContent className="flex-1 overflow-y-auto space-y-1">
          {sessions.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setSessionId(s.id)}
              className={`w-full rounded-md px-2 py-1.5 text-left text-xs ${
                s.id === sessionId
                  ? "bg-primary text-primary-foreground"
                  : "hover:bg-neutral-100 dark:hover:bg-neutral-800"
              }`}
            >
              <div className="font-medium">{s.title || "Untitled"}</div>
              <div className="text-[10px] opacity-70">
                {new Date(s.created_at).toLocaleString("ja-JP")}
              </div>
            </button>
          ))}
          {sessions.length === 0 && (
            <p className="text-xs text-muted-foreground">No sessions yet — type below.</p>
          )}
        </CardContent>
      </Card>

      <ChatInterface
        messages={messages}
        pending={pending}
        inFlightAssistantText={inFlightAssistantText}
        inFlightToolCalls={inFlightToolCalls}
        onSend={handleSend}
      />
      <ScratchpadPane artifacts={artifacts} />
    </div>
  );
}
