# Architecture

The assistant uses a hierarchy rather than treating chat transcripts as one memory store:

1. Current conversation context
2. Structured active state for appointments, deadlines, trips, deliveries, tasks, and pending replies
3. Compact user and durable-memory summaries
4. Entity, assertion, relationship, episode, and document records in SQLite
5. Daily notes and historical episodes
6. Original searchable session history

Native memory search combines lexical FTS and vector similarity. Local Ollama provides embeddings only; the connected Codex model performs ordinary reasoning. Background cognition enriches meaningful completed turns without delaying the visible response. Nightly consolidation may promote grounded recurring information while preserving historical records.

The acknowledgement sidecar uses an isolated ephemeral Luna turn. It does not receive conversation history or memory and must never answer the request; it provides only a short, source-neutral progress acknowledgement.
