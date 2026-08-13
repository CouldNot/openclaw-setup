# Structured memory schema

The SQLite knowledge map complements native OpenClaw Markdown memory. It is not the source for secrets or raw transcripts.

## Records

- `entities`: stable identities and aliases for people, projects, organizations, places, goals, interests, preferences, decisions, commitments, events, documents, topics, courses, trips, and opportunities.
- `relationships`: explicit typed edges with temporal validity, confidence, status, provenance, and optional supersession.
- `assertions`: subject/predicate/value memories with confidence, importance, validity interval, status, source, and supersession.
- `episodes`: durable historical events/conversations with date, summary, decision, concerns, outcome, and source reference.
- `episode_entities`: episode-to-entity links and roles.
- `documents`: original-document references and extracted-summary metadata.
- `reminders`: contextual reminder records; OpenClaw cron remains the execution source of truth.
- `audit_log`: append-only mutation/retrieval diagnostics. Deletion audits contain identifiers and reason, not deleted content.

## Status semantics

- `tentative`: considered or possible, not established.
- `likely`: supported but not explicit or fully confirmed.
- `confirmed`: directly established.
- `outdated`: no longer current without a specific replacing record.
- `superseded`: replaced by a newer assertion or edge.
- `disputed`: conflicting and unresolved.
- `deleted`: tombstoned and excluded from normal retrieval.

Current-state retrieval excludes outdated, superseded, disputed, and deleted records unless historical intent is explicit. Historical retrieval may include all except deleted records.

## Provenance authority

Default authority order: explicit user statement/instruction; user-authored document; calendar/contact/email fact; trusted tool output; web source; assistant inference. Confidence and direct correction can override this ordering.

## Temporal rules

Use `valid_from` and `valid_to` for when a fact was true, not merely when it was recorded. Use `observed_at` for discovery time. Never project a current state backward into an earlier period.
