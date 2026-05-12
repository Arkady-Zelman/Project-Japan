"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { getPosthog } from "@/lib/posthog";

export function PosthogProvider({ userId, email }: { userId?: string | null; email?: string | null }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    const ph = getPosthog();
    if (!ph) return;
    if (userId) {
      ph.identify(userId, email ? { email } : undefined);
    }
  }, [userId, email]);

  useEffect(() => {
    const ph = getPosthog();
    if (!ph) return;
    const search = searchParams?.toString();
    const url = pathname + (search ? `?${search}` : "");
    ph.capture("$pageview", { $current_url: url });
  }, [pathname, searchParams]);

  return null;
}
