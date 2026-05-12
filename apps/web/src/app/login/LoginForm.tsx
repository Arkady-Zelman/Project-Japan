"use client";

import { useState, type FormEvent } from "react";

import { createBrowserClient } from "@/lib/supabase/client";

type Props = { next: string };

export function LoginForm({ next }: Props) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!email) return;
    setStatus("sending");
    setError(null);

    const supabase = createBrowserClient();
    const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`;
    const { error: err } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: redirectTo },
    });
    if (err) {
      setStatus("error");
      setError(err.message);
      return;
    }
    setStatus("sent");
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <label className="block">
        <span className="text-sm font-medium text-neutral-700 dark:text-neutral-300">Email</span>
        <input
          type="email"
          required
          autoComplete="email"
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={status === "sending" || status === "sent"}
          className="mt-1 block w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-neutral-400 disabled:opacity-50 dark:border-neutral-700 dark:bg-neutral-950"
          placeholder="you@example.com"
        />
      </label>
      <button
        type="submit"
        disabled={status === "sending" || status === "sent"}
        className="w-full rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
      >
        {status === "sending" ? "Sending..." : status === "sent" ? "Check your inbox" : "Send magic link"}
      </button>
      {status === "sent" && (
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          We sent a link to <span className="font-medium">{email}</span>. Click it to sign in.
        </p>
      )}
      {status === "error" && error && (
        <p className="text-sm text-red-600">{error}</p>
      )}
    </form>
  );
}
