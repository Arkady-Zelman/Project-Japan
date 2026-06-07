const DEFAULT_NEXT_PATH = "/workbench";

export function sanitizeNextPath(
  value: string | null | undefined,
  fallback = DEFAULT_NEXT_PATH,
): string {
  if (!value) return fallback;

  const trimmed = value.trim();
  if (
    !trimmed.startsWith("/") ||
    trimmed.startsWith("//") ||
    trimmed.includes("\\")
  ) {
    return fallback;
  }

  try {
    const base = "https://jepx-storage.local";
    const parsed = new URL(trimmed, base);
    if (parsed.origin !== base) return fallback;
    return `${parsed.pathname}${parsed.search}${parsed.hash}` || fallback;
  } catch {
    return fallback;
  }
}
