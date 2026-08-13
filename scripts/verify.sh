#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
"$repo_dir/scripts/audit-repo.sh"
python3 -m py_compile "$repo_dir"/workspace/skills/second-brain/scripts/*.py "$repo_dir"/extensions/background-cognition/cognition_worker.py
python3 -m unittest "$repo_dir/tests/test_second_brain.py"
for file in "$repo_dir"/extensions/*/index.js; do
  if command -v node >/dev/null; then node --check "$file"; fi
done
python3 - <<'PY' "$repo_dir/config/openclaw.json.tmpl"
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); text=p.read_text()
for key in ('__OPENCLAW_HOME__','__OWNER_DISCORD_ID__','__OWNER_TIMEZONE__','__DISCORD_GUILD_ID__','__GATEWAY_TOKEN__'):
    text=text.replace(key,'placeholder')
json.loads(text)
PY
echo "Verification passed."
