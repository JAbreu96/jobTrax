#!/usr/bin/env bash
# Print GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN for an MCP
# account, ready to paste into a hosted MCP env form.
# WARNING: without --mask the output contains live secrets. Do not redirect to a file.
set -euo pipefail

usage() {
  cat <<'USAGE'
usage: print-google-mcp-env.sh [account] [--mask] [--export]

accounts:
  gtasks      (default)  ~/.config/gtasks-mcp/token.json
  gtasks-alt             ~/.config/gtasks-mcp/token-alt.json
  gmail                  ~/.gmail-mcp/credentials.json
  gmail-alt              ~/.gmail-mcp/credentials-alt.json

options:
  --mask     show only the first 6 / last 4 characters of each value
  --export   emit "export KEY='value'" lines instead of KEY=value
USAGE
}

account=gtasks
mask=0
export_fmt=0

for arg in "$@"; do
  case "$arg" in
    --mask)    mask=1 ;;
    --export)  export_fmt=1 ;;
    -h|--help) usage; exit 0 ;;
    -*)        echo "unknown option: $arg" >&2; usage >&2; exit 2 ;;
    *)         account="$arg" ;;
  esac
done

gtasks_dir="$HOME/.config/gtasks-mcp"
gmail_dir="$HOME/.gmail-mcp"

case "$account" in
  gtasks)     keys="$gtasks_dir/gcp-oauth.keys.json"; token="$gtasks_dir/token.json"
              hint="run the gtasks MCP server once to complete the OAuth flow" ;;
  gtasks-alt) keys="$gtasks_dir/gcp-oauth.keys.json"; token="$gtasks_dir/token-alt.json"
              hint="run the gtasks MCP server once with GTASKS_TOKEN_PATH=$gtasks_dir/token-alt.json" ;;
  gmail)      keys="$gmail_dir/gcp-oauth.keys.json"; token="$gmail_dir/credentials.json"
              hint="npx @gongrzhe/server-gmail-autoauth-mcp auth" ;;
  gmail-alt)  keys="$gmail_dir/gcp-oauth.keys.json"; token="$gmail_dir/credentials-alt.json"
              hint="GMAIL_CREDENTIALS_PATH=$gmail_dir/credentials-alt.json npx @gongrzhe/server-gmail-autoauth-mcp auth" ;;
  *)          echo "unknown account: $account" >&2; usage >&2; exit 2 ;;
esac

# read_json_key FILE DOTTED_PATH...  -> prints the first non-empty string match
read_json_key() {
  python3 - "$@" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except Exception:
    sys.exit(1)
for dotted in sys.argv[2:]:
    cur = data
    for part in dotted.split('.'):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            cur = None
            break
    if isinstance(cur, str) and cur:
        print(cur)
        sys.exit(0)
sys.exit(1)
PY
}

warn_if_world_readable() {
  local f="$1" mode
  [ -f "$f" ] || return 0
  mode=$(stat -f '%Lp' "$f" 2>/dev/null || stat -c '%a' "$f" 2>/dev/null) || return 0
  if (( 8#$mode & 4 )); then
    echo "warning: $f is mode $mode (world-readable) — consider: chmod 600 $f" >&2
  fi
}

status=0

emit() {
  local name="$1" value="$2"
  if [ -z "$value" ]; then
    return
  fi
  if (( mask )); then
    if (( ${#value} > 12 )); then
      value="${value:0:6}…${value: -4} (${#value} chars)"
    else
      value="… ${#value} chars"
    fi
  fi
  if (( export_fmt )); then
    printf "export %s='%s'\n" "$name" "$value"
  else
    printf '%s=%s\n' "$name" "$value"
  fi
}

fetch() {  # fetch VAR_NAME FILE DOTTED_PATH...
  local name="$1" file="$2"; shift 2
  local value=""
  if [ ! -f "$file" ]; then
    echo "$name: missing file $file — $hint" >&2
    status=1
  elif ! value=$(read_json_key "$file" "$@"); then
    echo "$name: not found in $file" >&2
    status=1
    value=""
  fi
  emit "$name" "$value"
}

warn_if_world_readable "$keys"
warn_if_world_readable "$token"

fetch GOOGLE_CLIENT_ID     "$keys"  installed.client_id     web.client_id     client_id
fetch GOOGLE_CLIENT_SECRET "$keys"  installed.client_secret web.client_secret client_secret
fetch GOOGLE_REFRESH_TOKEN "$token" refresh_token tokens.refresh_token credentials.refresh_token

exit $status
