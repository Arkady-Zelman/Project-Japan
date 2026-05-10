"use client";

import { useEffect, useRef, useState } from "react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  type ChatMessage,
  type ToolCallShape,
} from "@/hooks/useChatSession";

type Props = {
  messages: ChatMessage[];
  pending: boolean;
  inFlightAssistantText: string;
  inFlightToolCalls: ToolCallShape[];
  onSend: (text: string) => Promise<unknown>;
};

export function ChatInterface({
  messages,
  pending,
  inFlightAssistantText,
  inFlightToolCalls,
  onSend,
}: Props) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, inFlightAssistantText, inFlightToolCalls]);

  const submit = async () => {
    const text = input.trim();
    if (!text || pending) return;
    setInput("");
    await onSend(text);
  };

  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <CardTitle>Chat</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3">
          {messages.length === 0 && !pending && (
            <p className="text-sm text-muted-foreground">
              Try: <em>"What was Tokyo&apos;s average peak price (17:00–20:00) in August 2025?"</em>
            </p>
          )}
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}
          {pending && (inFlightAssistantText || inFlightToolCalls.length > 0) && (
            <InFlightBubble
              text={inFlightAssistantText}
              toolCalls={inFlightToolCalls}
            />
          )}
        </div>
        <div className="flex gap-2">
          <textarea
            className="min-h-[60px] flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Ask the analyst… (⌘+Enter to send)"
            disabled={pending}
          />
          <button
            type="button"
            onClick={submit}
            disabled={!input.trim() || pending}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {pending ? "Thinking…" : "Send"}
          </button>
        </div>
      </CardContent>
    </Card>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const isTool = message.role === "tool";
  if (isTool) {
    return (
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">tool results ({message.tool_results?.length ?? 0})</summary>
        <pre className="mt-1 overflow-x-auto rounded bg-neutral-50 p-2 dark:bg-neutral-900">
          {JSON.stringify(message.tool_results, null, 2)}
        </pre>
      </details>
    );
  }
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-md px-3 py-2 text-sm ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-neutral-100 dark:bg-neutral-800"
        }`}
      >
        {message.content && (
          <div className="whitespace-pre-wrap">{message.content}</div>
        )}
        {message.tool_calls && message.tool_calls.length > 0 && (
          <details className="mt-2 text-xs opacity-80">
            <summary className="cursor-pointer">
              {message.tool_calls.length} tool call
              {message.tool_calls.length === 1 ? "" : "s"}
            </summary>
            <ul className="mt-1 space-y-1">
              {message.tool_calls.map((tc) => (
                <li key={tc.id} className="font-mono">
                  {tc.name}({JSON.stringify(tc.arguments).slice(0, 120)}
                  {JSON.stringify(tc.arguments).length > 120 ? "…)" : ")"}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}

function InFlightBubble({
  text, toolCalls,
}: { text: string; toolCalls: ToolCallShape[] }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-md bg-neutral-100 px-3 py-2 text-sm dark:bg-neutral-800">
        {text && <div className="whitespace-pre-wrap">{text}</div>}
        {toolCalls.length > 0 && (
          <p className="mt-2 text-xs italic opacity-80">
            calling: {toolCalls.map((tc) => tc.name).join(", ")}…
          </p>
        )}
        {!text && toolCalls.length === 0 && (
          <p className="text-xs italic opacity-80">thinking…</p>
        )}
      </div>
    </div>
  );
}
