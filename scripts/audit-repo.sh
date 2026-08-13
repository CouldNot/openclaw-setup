#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_dir"

for forbidden in memory backups sessions state .private; do
  if find . -path './.git' -prune -o -type d -name "$forbidden" -print | grep -q .; then
    echo "Forbidden data directory present: $forbidden" >&2; exit 1
  fi
done
if find . -path './.git' -prune -o -type f \( -name '*.sqlite*' -o -name '*.db' -o -name 'credentials.json' -o -name 'auth.json' -o -name '*.pem' -o -name '*.key' \) -print | grep -q .; then
  echo "Forbidden credential/database artifact present" >&2; exit 1
fi

patterns='(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9_-]{20,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|[0-9]{17,20}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{20,})'
if rg -n --hidden -g '!.git/**' -g '!.env.example' "$patterns" .; then
  echo "Possible credential detected" >&2; exit 1
fi

if rg -n --hidden -g '!.git/**' -g '!scripts/audit-repo.sh' '(ddale1128|daledai@|824653557894479972|1536587041616433202|South Surrey|Trackside)' .; then
  echo "Known personal value detected" >&2; exit 1
fi
echo "Repository privacy audit passed."
