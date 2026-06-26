const DEFAULT_NEXT_PATH = "/workbench";

export function sanitizeNextPath(next: string | null | undefined): string {
  if (!next) return DEFAULT_NEXT_PATH;

  let decoded = next;
  try {
    decoded = decodeURIComponent(next);
  } catch {
    return DEFAULT_NEXT_PATH;
  }

  if (
    !decoded.startsWith("/") ||
    decoded.startsWith("//") ||
    decoded.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(decoded)
  ) {
    return DEFAULT_NEXT_PATH;
  }

  return decoded;
}
