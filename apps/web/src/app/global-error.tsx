"use client";

import * as Sentry from "@sentry/nextjs";
import Link from "next/link";
import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html>
      <body>
        <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-12 text-center">
          <p className="text-xs uppercase tracking-wider text-neutral-500">500</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">Something went wrong</h1>
          <p className="mt-3 text-sm text-neutral-500">
            An unexpected error occurred. It&apos;s been logged; sorry about that.
          </p>
          {error.digest && (
            <p className="mt-2 font-mono text-xs text-neutral-400">digest: {error.digest}</p>
          )}
          <div className="mt-6 flex justify-center gap-3">
            <button
              onClick={() => reset()}
              className="inline-flex rounded-md border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-900 hover:bg-neutral-50"
            >
              Try again
            </button>
            <Link
              href="/dashboard"
              className="inline-flex rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700"
            >
              Go to dashboard
            </Link>
          </div>
        </main>
      </body>
    </html>
  );
}
