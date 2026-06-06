/**
 * Layout shared by /dashboard, /workbench, /lab.
 *
 * Renders a top nav with the app brand, route links, a language switcher,
 * and a session-aware sign-in / sign-out widget on the right.
 */

import { Suspense } from "react";

import { createSessionClient } from "@/lib/supabase/server";
import { PosthogProvider } from "@/components/PosthogProvider";
import { AppHeader } from "@/components/AppHeader";

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
      <AppHeader userEmail={user?.email ?? null} signedIn={!!user} />
      {children}
    </>
  );
}
