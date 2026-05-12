/**
 * /workbench — M7 LSM valuation runner.
 *
 * Server Component shell: gates on auth (middleware also redirects, this is
 * defense-in-depth) then renders the client-side WorkbenchClient.
 */

import { redirect } from "next/navigation";

import { createSessionClient } from "@/lib/supabase/server";
import { PageHeader } from "@/components/ui/page-header";
import { WorkbenchClient } from "@/components/workbench/WorkbenchClient";

export const dynamic = "force-dynamic";

export default async function WorkbenchPage() {
  const session = createSessionClient();
  const { data } = await session.auth.getUser();
  if (!data.user) redirect("/login?next=/workbench");

  return (
    <main className="mx-auto max-w-7xl px-6 py-12">
      <PageHeader
        title="Workbench"
        description="Configure a storage asset and run a Boogert-de Jong LSM valuation against the latest forecast paths. Results stream in live via Supabase Realtime."
      />
      <WorkbenchClient />
    </main>
  );
}
