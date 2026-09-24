#!/bin/bash
#
# Build frontend/ into src/static/dist/, which is what /app serves.
#
# That directory is gitignored, so it does not exist on a fresh clone and /app
# has nothing to serve until this runs once. Run it again after any change
# under frontend/ -- there is no watcher in this path (use `npm run dev` for
# that).
#
# The Node floor is the reason this is a script rather than a README line.
# Several of this repo's launchd wrappers pin PATH to node v18, and Vite 7
# needs >= 20.19: run `npm install` under v18 and it fails partway through
# with an error that names neither Node nor the version, which is a genuinely
# confusing half-hour. .nvmrc pins the version this expects.

set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Opt into nvm when it is present, so this works without the caller having
# already run `nvm use`. Not required: any Node on PATH that clears the floor
# below is fine, which is what CI or a Homebrew install would give.
if [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
  # shellcheck disable=SC1091
  . "${NVM_DIR:-$HOME/.nvm}/nvm.sh"
  nvm use >/dev/null 2>&1 || {
    echo "nvm could not select the version in .nvmrc ($(cat .nvmrc))." >&2
    echo "Install it with:  nvm install" >&2
    exit 1
  }
fi

if ! command -v node >/dev/null 2>&1; then
  echo "node not found on PATH. Install Node $(cat .nvmrc) or newer." >&2
  exit 1
fi

MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
MINOR="$(node -p 'process.versions.node.split(".")[1]')"
if [ "$MAJOR" -lt 20 ] || { [ "$MAJOR" -eq 20 ] && [ "$MINOR" -lt 19 ]; }; then
  echo "Node $(node --version) is too old -- Vite 7 needs >= 20.19." >&2
  echo "This repo pins $(cat .nvmrc) in .nvmrc:  nvm install && nvm use" >&2
  exit 1
fi

cd frontend

# `npm ci` would be the reflex here, but it deletes and reinstalls
# node_modules every run, which turns a two-second rebuild into a slow one for
# no benefit in a local dev loop. There is no lockfile-integrity requirement
# here that `npm install` does not already meet.
if [ ! -d node_modules ]; then
  echo "Installing frontend dependencies..."
  npm install
fi

npm run build

echo
echo "Built to src/static/dist/. Start the server and open http://127.0.0.1:5151/app"
