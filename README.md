# Portable OpenClaw Personal Assistant

Reproducible, secrets-free configuration for a Discord-first OpenClaw personal assistant with layered memory, active-state tracking, Gmail/Calendar integration, background cognition, hybrid retrieval, and conversational progress acknowledgements.

This repository intentionally contains infrastructure only. It does not contain personal memory, conversations, email, calendar data, OAuth credentials, Discord credentials, databases, indexes, logs, or backups.

## What it installs

- Sanitized OpenClaw configuration
- Personal-assistant workspace instructions
- Structured second-brain skill and schema
- Active-state, Gmail-readonly, and background-cognition extensions
- Hourly active-state lifecycle and background cognition timers
- Local Ollama embeddings with Codex/Luna for normal reasoning
- Setup verification and repository privacy scanning

## Fresh machine

1. Install Ubuntu, Git, Python 3, systemd user services, Ollama, OpenClaw, Codex CLI, and `gog`.
2. Clone this repository.
3. Copy `.env.example` to `.env` and fill the local values.
4. Run `./scripts/bootstrap.sh`.
5. Add the Discord token to `~/.openclaw/gateway.systemd.env`.
6. Authorize Google accounts interactively as described in `docs/GOOGLE.md`.
7. Run `./scripts/verify.sh`.

The bootstrap script refuses to overwrite an existing installation unless `--force` is explicitly supplied. It does not install or restore personal memories.

## Security model

- Secrets remain in local environment files and credential stores.
- Gmail is authorized read-only; Calendar can be authorized read/write.
- The gateway runs as an unprivileged dedicated user.
- Public-facing service exposure is not configured here.
- The repository scan blocks common credentials, personal account values, memory artifacts, and databases.

Run `./scripts/audit-repo.sh` before every push.
