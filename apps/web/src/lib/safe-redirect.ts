const DEFAULT_REDIRECT_PATH = "/workbench";

export function safeRedirectPath(next: string | null | undefined): string {
  if (!next) {
    return DEFAULT_REDIRECT_PATH;
  }

  if (!next.startsWith("/") || next.startsWith("//")) {
    return DEFAULT_REDIRECT_PATH;
  }

  return next;
}
