#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
force=false
[[ ${1:-} == --force ]] && force=true

if [[ ! -f "$repo_dir/.env" ]]; then
  echo "Copy .env.example to .env and fill it first." >&2
  exit 1
fi
set -a
source "$repo_dir/.env"
set +a

target=${OPENCLAW_HOME:?OPENCLAW_HOME is required}
if [[ -e "$target/.openclaw/openclaw.json" && $force != true ]]; then
  echo "Existing OpenClaw configuration found. Re-run with --force only after preserving it." >&2
  exit 1
fi

staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT
python3 "$repo_dir/scripts/render.py" "$staging"

install -d -m 0700 "$target/.openclaw" "$target/.config/systemd/user"
cp -a "$staging/.openclaw/." "$target/.openclaw/"
cp -a "$staging/.config/systemd/user/." "$target/.config/systemd/user/"
chmod 0600 "$target/.openclaw/openclaw.json"
find "$target/.openclaw/workspace-personal/skills" -type f -path '*/scripts/*' -name '*.py' -exec chmod 0755 {} +

echo "Configuration rendered. Install/pin the versions in VERSION, authenticate Codex and Google locally, then enable the user services."
