export const DEFAULT_AUTH_REDIRECT = "/workbench";

export function sanitizeNextPath(next: string | null | undefined): string {
  if (!next) return DEFAULT_AUTH_REDIRECT;

  const candidate = next.trim();
  if (
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(candidate)
  ) {
    return DEFAULT_AUTH_REDIRECT;
  }

  return candidate;
}
