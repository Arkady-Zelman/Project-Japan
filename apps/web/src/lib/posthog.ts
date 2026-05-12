"use client";

import posthog from "posthog-js";

let _initialized = false;

export function getPosthog() {
  const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
  if (!key) return null;
  if (typeof window === "undefined") return null;
  if (!_initialized) {
    posthog.init(key, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://us.i.posthog.com",
      capture_pageview: false, // we fire $pageview manually from the provider on route change
      person_profiles: "identified_only",
    });
    _initialized = true;
  }
  return posthog;
}

export function captureEvent(name: string, props?: Record<string, unknown>) {
  const ph = getPosthog();
  if (!ph) return;
  ph.capture(name, props);
}
