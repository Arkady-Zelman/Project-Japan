#!/usr/bin/env bash
# vercel-env-sync.sh — push .env.local → Vercel env scopes.
#
# Usage (from apps/web):
#   ./scripts/vercel-env-sync.sh                   # uses ../../.env.local
#   ./scripts/vercel-env-sync.sh path/to/.env      # explicit path
#
# Prerequisites:
#   1. npm i -g vercel@latest
#   2. vercel login
#   3. From apps/web: vercel link   (creates .vercel/project.json)
#
# Notes:
#   - Reads values in your shell. Nothing is printed to stdout except key
#     names and add/skip status — never the values themselves.
#   - Idempotent against re-runs: if a key already exists in the target
#     scope, vercel env add returns non-zero and this script reports it.
#     To overwrite, run: vercel env rm KEY scope, then re-run this script.
#   - JEPX_DEV_USER_ID is pushed to *development scope only*. Setting it
#     in production would let anyone act as that UUID — never do that.

set -euo pipefail

ENV_FILE="${1:-../../.env.local}"

# --- preflight ---------------------------------------------------------------
if ! command -v vercel >/dev/null 2>&1; then
  echo "error: vercel CLI not found. install with: npm i -g vercel@latest" >&2
  exit 1
fi
if ! vercel whoami >/dev/null 2>&1; then
  echo "error: not logged in. run: vercel login" >&2
  exit 1
fi
if [ ! -f .vercel/project.json ]; then
  echo "error: project not linked. cd apps/web && vercel link" >&2
  exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "error: env file not found: $ENV_FILE" >&2
  exit 1
fi

# --- keys --------------------------------------------------------------------
# Generated from `grep -roh 'process\.env\.[A-Z_][A-Z0-9_]*' src` — every var
# the Next.js bundle actually references at build or runtime.
PROD_KEYS=(
  NEXT_PUBLIC_SUPABASE_URL
  NEXT_PUBLIC_SUPABASE_ANON_KEY
  SUPABASE_SERVICE_ROLE_KEY
  MODAL_LSM_ENDPOINT
  MODAL_BACKTEST_ENDPOINT
  MODAL_AGENT_ENDPOINT
  NEXT_PUBLIC_SENTRY_DSN
  SENTRY_DSN
  SENTRY_AUTH_TOKEN
  SENTRY_ORG
  SENTRY_PROJECT
  NEXT_PUBLIC_POSTHOG_KEY
  NEXT_PUBLIC_POSTHOG_HOST
)

# Dev-only keys (do NOT promote to preview/production)
DEV_ONLY_KEYS=(
  JEPX_DEV_USER_ID
)

# --- push helper -------------------------------------------------------------
# Parses `KEY=value` from $ENV_FILE, strips surrounding quotes, pipes to vercel.
push_key() {
  local key=$1
  local scope=$2
  local value
  value=$(grep -E "^${key}=" "$ENV_FILE" | head -1 | sed -E "s/^${key}=//; s/^['\"]//; s/['\"]$//" || true)

  if [ -z "${value:-}" ]; then
    printf "  skip   %-35s (no value in %s)\n" "$key" "$ENV_FILE"
    return
  fi

  if printf '%s' "$value" | vercel env add "$key" "$scope" >/dev/null 2>&1; then
    printf "  added  %-35s → %s\n" "$key" "$scope"
  else
    printf "  exists %-35s → %s  (rm first: vercel env rm %s %s)\n" \
      "$key" "$scope" "$key" "$scope"
  fi
}

# --- run ---------------------------------------------------------------------
echo "Reading from: $ENV_FILE"
echo "Vercel project: $(vercel whoami) → $(jq -r '.projectId // "unknown"' .vercel/project.json 2>/dev/null || echo unknown)"
echo ""
echo "Production scope:"
for k in "${PROD_KEYS[@]}"; do push_key "$k" production; done

echo ""
echo "Development scope (local-dev convenience only):"
for k in "${DEV_ONLY_KEYS[@]}"; do push_key "$k" development; done

echo ""
echo "Done. To take effect on a running deployment:"
echo "  vercel --prod --force"
echo ""
echo "To copy production → preview (so PR previews talk to prod Supabase):"
echo "  for k in ${PROD_KEYS[*]}; do"
echo "    vercel env pull --environment=production .env.tmp"
echo "    val=\$(grep -E \"^\${k}=\" .env.tmp | sed -E \"s/^[^=]+=//; s/^['\\\"]//; s/['\\\"]\$//\")"
echo "    printf '%s' \"\$val\" | vercel env add \"\$k\" preview"
echo "  done"
echo "  rm .env.tmp"
