/**
 * Layout shared by /dashboard, /workbench, /lab.
 *
 * Renders a top nav with the app brand, route links, and a session-aware
 * sign-in / sign-out widget on the right.
 */

import Link from "next/link";
import { Suspense } from "react";

import { createSessionClient } from "@/lib/supabase/server";
import { PosthogProvider } from "@/components/PosthogProvider";

export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const supabase = createSessionClient();
  const { data } = await supabase.auth.getUser();
  const user = data.user;

  return (
    <>
      <Suspense fallback={null}>
        <PosthogProvider userId={user?.id ?? null} email={user?.email ?? null} />
      </Suspense>
      <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-[linear-gradient(180deg,rgba(15,15,18,0.78),rgba(15,15,18,0.62))] backdrop-blur-[18px] backdrop-saturate-[1.2] shadow-[0_1px_0_rgba(255,255,255,0.04)]">
        <div className="mx-auto flex h-[60px] w-full max-w-[1600px] items-center justify-between gap-3 px-7">
          <nav className="flex items-center gap-6 text-sm">
            <Link
              href="/dashboard"
              className="inline-flex items-center gap-2.5 font-semibold tracking-tight"
            >
              <span
                aria-hidden
                className="inline-block size-2 rounded-full bg-[radial-gradient(circle_at_30%_30%,#fda4af,#be123c_70%)] shadow-[0_0_8px_rgba(244,63,94,0.55)]"
              />
              JEPX-Storage
            </Link>
            <Link href="/dashboard" className="text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100">Dashboard</Link>
            <Link href="/workbench" className="text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100">Workbench</Link>
            <Link href="/lab" className="text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100">Lab</Link>
          </nav>
          <div className="flex items-center gap-3 text-sm">
            {user ? (
              <>
                <span className="hidden text-neutral-500 sm:inline">{user.email}</span>
                <form action="/auth/signout" method="post">
                  <button
                    type="submit"
                    className="rounded-md border border-neutral-300 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-900"
                  >
                    Sign out
                  </button>
                </form>
              </>
            ) : (
              <Link
                href="/login"
                className="rounded-md border border-neutral-300 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-900"
              >
                Sign in
              </Link>
            )}
          </div>
        </div>
      </header>
      {children}
    </>
  );
}
