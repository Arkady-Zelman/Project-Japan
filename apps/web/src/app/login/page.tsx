/**
 * /login — email magic-link sign-in.
 *
 * Supabase email provider sends a one-time link to the user's inbox; clicking
 * it lands at /auth/callback which exchanges the code for a session cookie.
 *
 * `next` query param is preserved through the round-trip so the user lands
 * back on the page they were trying to reach.
 */

import { PageHeader } from "@/components/ui/page-header";
import { LoginForm } from "./LoginForm";

export const dynamic = "force-dynamic";

type Props = {
  searchParams: { next?: string };
};

export default function LoginPage({ searchParams }: Props) {
  const next = searchParams.next ?? "/workbench";
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-12">
      <PageHeader
        title="Sign in"
        description="Enter your email; we'll send you a magic link. No password required."
      />
      <div className="rounded-xl bg-card p-6 ring-1 ring-foreground/10">
        <LoginForm next={next} />
      </div>
    </main>
  );
}
