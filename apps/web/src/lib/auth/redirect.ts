const DEFAULT_NEXT_PATH = "/workbench";
const SAME_ORIGIN_BASE = "https://jepx-storage.invalid";
const CONTROL_OR_BACKSLASH = /[\u0000-\u001F\u007F\\]/;

export function sanitizeNextPath(
  next: string | null | undefined,
  fallback = DEFAULT_NEXT_PATH,
): string {
  if (!next) return fallback;
  if (!next.startsWith("/") || next.startsWith("//")) return fallback;
  if (CONTROL_OR_BACKSLASH.test(next)) return fallback;

  try {
    const parsed = new URL(next, SAME_ORIGIN_BASE);
    if (parsed.origin !== SAME_ORIGIN_BASE) return fallback;
    const sanitized = `${parsed.pathname}${parsed.search}${parsed.hash}`;
    if (!sanitized.startsWith("/") || sanitized.startsWith("//")) return fallback;
    return sanitized;
  } catch {
    return fallback;
  }
}
