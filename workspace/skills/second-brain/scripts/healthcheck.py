#!/usr/bin/env python3
"""Fail-fast checks for local second-brain persistence."""
import json, sqlite3, urllib.request
from pathlib import Path

home=Path.home(); ws=home/".openclaw/workspace-personal"; issues=[]
for p in (ws/"USER.md",ws/"MEMORY.md",ws/"DREAMS.md",ws/"SECOND_BRAIN.md",ws/"memory",ws/"memory/knowledge/second-brain.sqlite"):
    if not p.exists(): issues.append(f"missing:{p}")
try:
    db=sqlite3.connect(f"file:{ws/'memory/knowledge/second-brain.sqlite'}?mode=ro",uri=True)
    if db.execute("pragma integrity_check").fetchone()[0]!="ok": issues.append("knowledge-db-integrity")
    db.close()
except Exception as e: issues.append(f"knowledge-db:{e}")
try:
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",timeout=3) as r:
        names={m["name"].split(":")[0] for m in json.load(r).get("models",[])}
        if "nomic-embed-text" not in names: issues.append("embedding-model-missing")
except Exception as e: issues.append(f"ollama:{e}")
print(json.dumps({"ok":not issues,"issues":issues}))
raise SystemExit(bool(issues))
