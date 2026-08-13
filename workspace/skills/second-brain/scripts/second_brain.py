#!/usr/bin/env python3
"""Deterministic personal knowledge-map operations for OpenClaw."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import sys
import uuid
from pathlib import Path

DEFAULT_DB = Path.home() / ".openclaw/workspace-personal/memory/knowledge/second-brain.sqlite"
VALID_TYPES = {
    "PERSON", "PROJECT", "ORGANIZATION", "PLACE", "GOAL", "INTEREST",
    "PREFERENCE", "DECISION", "COMMITMENT", "EVENT", "DOCUMENT", "TOPIC",
    "COURSE", "TRIP", "OPPORTUNITY", "USER",
}
VALID_STATUS = {"tentative", "likely", "confirmed", "outdated", "superseded", "disputed", "deleted"}
ACTIVE_STATUS = {"tentative", "scheduled", "imminent", "awaiting_confirmation", "overdue", "completed", "cancelled", "missed", "deleted"}


def score(value):
    """Accept a 0..1 score or a human-friendly importance/confidence label."""
    labels = {"low": 0.25, "normal": 0.5, "medium": 0.5, "high": 0.75, "critical": 1.0}
    if isinstance(value, str) and value.strip().lower() in labels:
        return labels[value.strip().lower()]
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be 0..1 or low, normal, high, critical")
    if not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return parsed


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def ident(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    return db


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS entities(
 id TEXT PRIMARY KEY, type TEXT NOT NULL, canonical_name TEXT NOT NULL,
 normalized_name TEXT NOT NULL, aliases_json TEXT NOT NULL DEFAULT '[]',
 description TEXT, status TEXT NOT NULL DEFAULT 'confirmed', confidence REAL NOT NULL DEFAULT .9,
 first_observed TEXT NOT NULL, last_confirmed TEXT, source_kind TEXT NOT NULL,
 source_ref TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(type, normalized_name), CHECK(confidence BETWEEN 0 AND 1)
);
CREATE TABLE IF NOT EXISTS relationships(
 id TEXT PRIMARY KEY, subject_id TEXT NOT NULL REFERENCES entities(id), predicate TEXT NOT NULL,
 object_id TEXT NOT NULL REFERENCES entities(id), status TEXT NOT NULL DEFAULT 'confirmed',
 confidence REAL NOT NULL DEFAULT .9, importance REAL NOT NULL DEFAULT .5,
 valid_from TEXT, valid_to TEXT, observed_at TEXT NOT NULL, source_kind TEXT NOT NULL,
 source_ref TEXT, supersedes_id TEXT REFERENCES relationships(id), created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, CHECK(confidence BETWEEN 0 AND 1), CHECK(importance BETWEEN 0 AND 1)
);
CREATE TABLE IF NOT EXISTS assertions(
 id TEXT PRIMARY KEY, subject_id TEXT NOT NULL REFERENCES entities(id), predicate TEXT NOT NULL,
 value_json TEXT NOT NULL, category TEXT, status TEXT NOT NULL DEFAULT 'confirmed',
 confidence REAL NOT NULL DEFAULT .9, importance REAL NOT NULL DEFAULT .5,
 valid_from TEXT, valid_to TEXT, observed_at TEXT NOT NULL, last_confirmed TEXT,
 source_kind TEXT NOT NULL, source_ref TEXT, supersedes_id TEXT REFERENCES assertions(id),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK(confidence BETWEEN 0 AND 1), CHECK(importance BETWEEN 0 AND 1)
);
CREATE TABLE IF NOT EXISTS episodes(
 id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, topic TEXT NOT NULL, summary TEXT NOT NULL,
 decision TEXT, concerns TEXT, outcome TEXT, importance REAL NOT NULL DEFAULT .6,
 source_kind TEXT NOT NULL, source_ref TEXT, markdown_path TEXT, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, CHECK(importance BETWEEN 0 AND 1)
);
CREATE TABLE IF NOT EXISTS episode_entities(
 episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
 entity_id TEXT NOT NULL REFERENCES entities(id), role TEXT,
 PRIMARY KEY(episode_id, entity_id, role)
);
CREATE TABLE IF NOT EXISTS documents(
 id TEXT PRIMARY KEY, entity_id TEXT REFERENCES entities(id), path TEXT NOT NULL,
 sha256 TEXT, title TEXT, source_kind TEXT NOT NULL, source_ref TEXT,
 received_at TEXT, summary TEXT, status TEXT NOT NULL DEFAULT 'confirmed', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders(
 id TEXT PRIMARY KEY, contextual_text TEXT NOT NULL, due_at TEXT, recurrence TEXT,
 cron_job_id TEXT, status TEXT NOT NULL DEFAULT 'confirmed', source_ref TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS active_items(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, summary TEXT,
 status TEXT NOT NULL DEFAULT 'tentative', starts_at TEXT, due_at TEXT,
 ends_at TEXT, review_at TEXT, checkin_at TEXT, checkin_reason TEXT, checkin_sent_at TEXT,
 importance REAL NOT NULL DEFAULT .6,
 confidence REAL NOT NULL DEFAULT .9, source_kind TEXT NOT NULL,
 source_ref TEXT, entity_ids_json TEXT NOT NULL DEFAULT '[]',
 topic_ids_json TEXT NOT NULL DEFAULT '[]', archive_policy TEXT NOT NULL DEFAULT 'episode',
 archived_episode_id TEXT REFERENCES episodes(id), created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, CHECK(importance BETWEEN 0 AND 1),
 CHECK(confidence BETWEEN 0 AND 1)
);
CREATE TABLE IF NOT EXISTS audit_log(
 id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, action TEXT NOT NULL,
 record_type TEXT, record_id TEXT, reason TEXT, source_ref TEXT, details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(normalized_name, status);
CREATE INDEX IF NOT EXISTS idx_rel_subject ON relationships(subject_id, predicate, status);
CREATE INDEX IF NOT EXISTS idx_rel_object ON relationships(object_id, predicate, status);
CREATE INDEX IF NOT EXISTS idx_assert_subject ON assertions(subject_id, predicate, status);
CREATE INDEX IF NOT EXISTS idx_assert_temporal ON assertions(valid_from, valid_to, status);
CREATE INDEX IF NOT EXISTS idx_episode_date ON episodes(occurred_at);
CREATE INDEX IF NOT EXISTS idx_active_time ON active_items(status,starts_at,due_at,review_at);
"""

def migrate(db):
    columns = {r[1] for r in db.execute("PRAGMA table_info(active_items)")}
    for name in ("checkin_at", "checkin_reason", "checkin_sent_at"):
        if name not in columns: db.execute(f"ALTER TABLE active_items ADD COLUMN {name} TEXT")
    db.commit()


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def emit(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def audit(db, action, record_type=None, record_id=None, reason=None, source_ref=None, details=None):
    db.execute("INSERT INTO audit_log(at,action,record_type,record_id,reason,source_ref,details_json) VALUES(?,?,?,?,?,?,?)",
               (now(), action, record_type, record_id, reason, source_ref, json.dumps(details or {}, ensure_ascii=False)))


def entity_by_ref(db, ref: str):
    row = db.execute("SELECT * FROM entities WHERE id=? AND status!='deleted'", (ref,)).fetchone()
    if row:
        return row
    n = norm(ref)
    if n in {"user", "dale", "dale dai"}:
        row = db.execute("SELECT * FROM entities WHERE id='user' AND status!='deleted'").fetchone()
        if row:
            return row
    rows = db.execute("SELECT * FROM entities WHERE normalized_name=? AND status!='deleted'", (n,)).fetchall()
    if len(rows) == 1:
        return rows[0]
    alias = [r for r in db.execute("SELECT * FROM entities WHERE status!='deleted'") if n in [norm(x) for x in json.loads(r["aliases_json"])]]
    if len(alias) == 1:
        return alias[0]
    if len(rows) + len(alias) > 1:
        raise SystemExit(f"ambiguous entity reference: {ref}")
    raise SystemExit(f"entity not found: {ref}")


def cmd_init(db, _):
    db.executescript(SCHEMA)
    stamp = now()
    db.execute("INSERT OR IGNORE INTO entities(id,type,canonical_name,normalized_name,status,confidence,first_observed,last_confirmed,source_kind,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               ("user", "USER", "User", "user", "confirmed", 1.0, stamp, stamp, "system", stamp, stamp))
    audit(db, "initialize", "database", "second-brain")
    db.commit()
    emit({"ok": True, "schema_version": 1})


def cmd_entity(db, a):
    a.type = a.type.upper()
    if a.type not in VALID_TYPES:
        raise SystemExit(f"invalid entity type: {a.type}")
    stamp, n = now(), norm(a.name)
    existing = db.execute("SELECT * FROM entities WHERE type=? AND normalized_name=?", (a.type, n)).fetchone()
    aliases = sorted(set(a.alias or []))
    if existing:
        merged = sorted(set(json.loads(existing["aliases_json"]) + aliases))
        db.execute("UPDATE entities SET aliases_json=?,description=COALESCE(?,description),status=?,confidence=?,last_confirmed=?,source_kind=?,source_ref=?,updated_at=? WHERE id=?",
                   (json.dumps(merged), a.description, a.status, a.confidence, stamp, a.source_kind, a.source_ref, stamp, existing["id"]))
        eid, action = existing["id"], "update_entity"
    else:
        eid = ident("ent")
        db.execute("INSERT INTO entities VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (eid, a.type, a.name.strip(), n, json.dumps(aliases), a.description, a.status, a.confidence, stamp, stamp, a.source_kind, a.source_ref, stamp, stamp))
        action = "create_entity"
    audit(db, action, "entity", eid, source_ref=a.source_ref, details={"type": a.type, "name": a.name})
    db.commit(); emit(dict(db.execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()))


def cmd_relate(db, a):
    s, o, stamp = entity_by_ref(db, a.subject), entity_by_ref(db, a.object), now()
    rid = ident("rel")
    db.execute("INSERT INTO relationships VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (rid, s["id"], a.predicate, o["id"], a.status, a.confidence, a.importance,
                a.valid_from, a.valid_to, stamp, a.source_kind, a.source_ref, None, stamp, stamp))
    audit(db, "create_relationship", "relationship", rid, source_ref=a.source_ref,
          details={"subject": s["canonical_name"], "predicate": a.predicate, "object": o["canonical_name"]})
    db.commit(); emit({"id": rid, "subject_id": s["id"], "predicate": a.predicate, "object_id": o["id"]})


def cmd_remember(db, a):
    s, stamp = entity_by_ref(db, a.subject), now()
    aid = ident("ast")
    value = json.loads(a.value) if a.json else a.value
    db.execute("INSERT INTO assertions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (aid, s["id"], a.predicate, json.dumps(value, ensure_ascii=False), a.category,
                a.status, a.confidence, a.importance, a.valid_from, a.valid_to, stamp,
                stamp if a.status == "confirmed" else None, a.source_kind, a.source_ref, None, stamp, stamp))
    audit(db, "create_assertion", "assertion", aid, source_ref=a.source_ref,
          details={"subject": s["canonical_name"], "predicate": a.predicate, "status": a.status})
    db.commit(); emit(dict(db.execute("SELECT * FROM assertions WHERE id=?", (aid,)).fetchone()))


def cmd_supersede(db, a):
    old = db.execute("SELECT * FROM assertions WHERE id=? AND status!='deleted'", (a.old_id,)).fetchone()
    if not old: raise SystemExit("old assertion not found")
    stamp, aid = now(), ident("ast")
    value = json.loads(a.value) if a.json else a.value
    db.execute("UPDATE assertions SET status='superseded',valid_to=COALESCE(valid_to,?),updated_at=? WHERE id=?", (a.valid_from or stamp, stamp, a.old_id))
    db.execute("INSERT INTO assertions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (aid, old["subject_id"], old["predicate"], json.dumps(value, ensure_ascii=False), old["category"],
                a.status, a.confidence, a.importance, a.valid_from or stamp, None, stamp,
                stamp if a.status == "confirmed" else None, a.source_kind, a.source_ref, a.old_id, stamp, stamp))
    audit(db, "supersede_assertion", "assertion", aid, reason=a.reason, source_ref=a.source_ref, details={"supersedes": a.old_id})
    db.commit(); emit({"id": aid, "supersedes": a.old_id})


def cmd_episode(db, a):
    eid, stamp = ident("ep"), now()
    db.execute("INSERT INTO episodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (eid, a.occurred_at, a.topic, a.summary, a.decision, a.concerns, a.outcome,
                a.importance, a.source_kind, a.source_ref, a.markdown_path, stamp, stamp))
    for ref in a.entity or []:
        e = entity_by_ref(db, ref)
        db.execute("INSERT OR IGNORE INTO episode_entities VALUES(?,?,?)", (eid, e["id"], None))
    audit(db, "create_episode", "episode", eid, source_ref=a.source_ref, details={"topic": a.topic, "occurred_at": a.occurred_at})
    db.commit(); emit({"id": eid, "occurred_at": a.occurred_at, "topic": a.topic})


def cmd_forget(db, a):
    stamp = now(); counts = {}
    if a.record_id:
        for table in ("assertions", "relationships", "entities", "documents", "reminders", "active_items"):
            cur = db.execute(f"UPDATE {table} SET status='deleted' WHERE id=?", (a.record_id,))
            if cur.rowcount: counts[table] = cur.rowcount
    elif a.entity:
        e = entity_by_ref(db, a.entity)
        for table, col in (("assertions","subject_id"),("relationships","subject_id"),("relationships","object_id")):
            cur = db.execute(f"UPDATE {table} SET status='deleted' WHERE {col}=?", (e["id"],))
            counts[table] = counts.get(table, 0) + cur.rowcount
        cur = db.execute("UPDATE entities SET status='deleted',description=NULL,aliases_json='[]',updated_at=? WHERE id=?", (stamp, e["id"]))
        counts["entities"] = cur.rowcount
        a.record_id = e["id"]
    else:
        raise SystemExit("provide --record-id or --entity")
    audit(db, "forget", "scope", a.record_id, reason=a.reason, source_ref=a.source_ref, details={"counts": counts})
    db.commit(); emit({"forgotten": counts, "record_id": a.record_id})


def cmd_search(db, a):
    q = f"%{norm(a.query)}%"; historical = a.historical
    statuses = "('tentative','likely','confirmed')" if not historical else "('tentative','likely','confirmed','outdated','superseded','disputed')"
    entities = [dict(r) for r in db.execute(f"SELECT * FROM entities WHERE status IN {statuses} AND (normalized_name LIKE ? OR aliases_json LIKE ? OR lower(coalesce(description,'')) LIKE ?) LIMIT ?", (q,q,q,a.limit))]
    assertions = [dict(r) for r in db.execute(f"SELECT a.*,e.canonical_name subject_name FROM assertions a JOIN entities e ON e.id=a.subject_id WHERE a.status IN {statuses} AND (lower(a.predicate) LIKE ? OR lower(a.value_json) LIKE ? OR lower(e.canonical_name) LIKE ?) ORDER BY a.importance DESC,a.observed_at DESC LIMIT ?", (q,q,q,a.limit))]
    relationships = [dict(r) for r in db.execute(f"SELECT r.*,s.canonical_name subject_name,o.canonical_name object_name FROM relationships r JOIN entities s ON s.id=r.subject_id JOIN entities o ON o.id=r.object_id WHERE r.status IN {statuses} AND (lower(s.canonical_name) LIKE ? OR lower(r.predicate) LIKE ? OR lower(o.canonical_name) LIKE ?) ORDER BY r.importance DESC,r.observed_at DESC LIMIT ?", (q,q,q,a.limit))]
    episodes = [dict(r) for r in db.execute("SELECT * FROM episodes WHERE lower(topic) LIKE ? OR lower(summary) LIKE ? OR lower(coalesce(decision,'')) LIKE ? OR lower(coalesce(concerns,'')) LIKE ? ORDER BY importance DESC,occurred_at DESC LIMIT ?", (q,q,q,q,a.limit))]
    audit(db, "search", "query", None, reason=a.query, details={"historical": historical, "counts": [len(entities),len(assertions),len(relationships),len(episodes)]})
    db.commit(); emit({"entities":entities,"assertions":assertions,"relationships":relationships,"episodes":episodes})


def cmd_history(db, a):
    e = entity_by_ref(db, a.entity)
    assertions = [dict(r) for r in db.execute("SELECT * FROM assertions WHERE subject_id=? AND status!='deleted' ORDER BY coalesce(valid_from,observed_at),observed_at", (e["id"],))]
    relationships = [dict(r) for r in db.execute("SELECT r.*,s.canonical_name subject_name,o.canonical_name object_name FROM relationships r JOIN entities s ON s.id=r.subject_id JOIN entities o ON o.id=r.object_id WHERE (r.subject_id=? OR r.object_id=?) AND r.status!='deleted' ORDER BY coalesce(r.valid_from,r.observed_at)", (e["id"],e["id"]))]
    episodes = [dict(r) for r in db.execute("SELECT ep.* FROM episodes ep JOIN episode_entities ee ON ee.episode_id=ep.id WHERE ee.entity_id=? ORDER BY ep.occurred_at", (e["id"],))]
    emit({"entity":dict(e),"assertions":assertions,"relationships":relationships,"episodes":episodes})


def cmd_audit(db, a):
    rows = [dict(r) for r in db.execute("SELECT * FROM audit_log WHERE (? IS NULL OR record_id=?) ORDER BY id DESC LIMIT ?", (a.record_id,a.record_id,a.limit))]
    emit(rows)


def parse_time(value):
    if not value: return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)

def default_checkin_delay(kind, title, summary):
    text = norm(" ".join(x for x in (kind, title, summary) if x))
    if any(x in text for x in ("medication", "medicine", "pill", "dose")): return dt.timedelta(minutes=15)
    if any(x in text for x in ("move-in", "move in", "trip", "flight", "wedding", "graduation")): return dt.timedelta(hours=5)
    if any(x in text for x in ("buy", "purchase", "shopping", "pickup")): return dt.timedelta(hours=3)
    if kind == "appointment": return dt.timedelta(hours=1)
    return dt.timedelta(hours=2)


def cmd_active_add(db, a):
    stamp, item_id = now(), ident("act")
    checkin_at, checkin_reason = a.checkin_at, a.checkin_reason
    if not checkin_at:
        end = parse_time(a.ends_at or a.starts_at or a.due_at)
        if end:
            grace = default_checkin_delay(a.kind,a.title,a.summary)
            checkin_at=(end+grace).isoformat(); checkin_reason=checkin_reason or f"Fallback timing: {int(grace.total_seconds()//60)} minutes after expected end"
    db.execute("INSERT INTO active_items(id,kind,title,summary,status,starts_at,due_at,ends_at,review_at,checkin_at,checkin_reason,checkin_sent_at,importance,confidence,source_kind,source_ref,entity_ids_json,topic_ids_json,archive_policy,archived_episode_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
      (item_id,a.kind,a.title,a.summary,a.status,a.starts_at,a.due_at,a.ends_at,a.review_at,checkin_at,checkin_reason,None,
       a.importance,a.confidence,a.source_kind,a.source_ref,json.dumps(a.entity or []),
       json.dumps(a.topic or []),a.archive_policy,None,stamp,stamp))
    audit(db,"create_active_item","active_item",item_id,source_ref=a.source_ref,
          details={"kind":a.kind,"title":a.title,"status":a.status})
    db.commit(); emit(dict(db.execute("SELECT * FROM active_items WHERE id=?",(item_id,)).fetchone()))


def cmd_active_list(db, a):
    stamp = parse_time(a.at) or dt.datetime.now(dt.timezone.utc)
    rows = [dict(r) for r in db.execute("SELECT * FROM active_items WHERE status!='deleted'")]
    if not a.historical: rows = [r for r in rows if r["status"] not in ("completed","cancelled","missed")]
    if a.kind: rows=[r for r in rows if norm(r["kind"]) == norm(a.kind)]
    if a.future_only:
        rows=[r for r in rows if (lambda when: when is not None and when >= stamp)(parse_time(r["starts_at"] or r["due_at"] or r["review_at"]))]
    query_hits={}
    if a.query:
        stop={"a","an","and","at","date","do","for","from","i","in","is","me","my","of","on","the","time","to","upcoming"}
        needles=[token for token in norm(a.query).split() if token not in stop and len(token)>1]
        for r in rows:
            hay=norm(r["title"]+" "+(r["summary"] or "")+" "+r["kind"]+" "+(r["source_ref"] or "")+" "+(r["topic_ids_json"] or ""))
            hits=sum(token in hay for token in needles)
            if hits: query_hits[r["id"]]=hits/max(1,len(needles))
        rows=[r for r in rows if r["id"] in query_hits]
    def score(r):
        when=parse_time(r["starts_at"] or r["due_at"] or r["review_at"])
        proximity=0 if not when else max(0, 1-abs((when-stamp).total_seconds())/(90*86400))
        state={"awaiting_confirmation":1.0,"overdue":.98,"imminent":.95,"scheduled":.75,"tentative":.45}.get(r["status"],.1)
        future_bonus=.5 if a.future_only and when else 0
        return r["importance"]*2+proximity+state+future_bonus+query_hits.get(r["id"],0)*2
    rows.sort(key=score,reverse=True)
    emit({"at":stamp.isoformat(),"items":rows[:a.limit]})


def cmd_active_update(db, a):
    stamp=now(); ids=a.ids or ([a.id] if a.id else [])
    if not ids: raise SystemExit("provide --id or --ids")
    found={r["id"] for r in db.execute(f"SELECT id FROM active_items WHERE id IN ({','.join('?' for _ in ids)})",ids)}
    missing=[item_id for item_id in ids if item_id not in found]
    if missing: raise SystemExit(f"active item not found: {', '.join(missing)}")
    mapping={"title":"title","summary":"summary","starts_at":"starts_at","due_at":"due_at","ends_at":"ends_at","review_at":"review_at","checkin_at":"checkin_at","checkin_reason":"checkin_reason"}
    changes={column:getattr(a,key) for key,column in mapping.items() if getattr(a,key) is not None}
    if not changes: raise SystemExit("provide at least one field to update")
    assignments=",".join(f"{column}=?" for column in changes)+",updated_at=?"
    for item_id in ids:
        db.execute(f"UPDATE active_items SET {assignments} WHERE id=?",[*changes.values(),stamp,item_id])
        audit(db,"update_active_item","active_item",item_id,reason=a.reason,details=changes)
    db.commit(); emit({"items":[dict(db.execute("SELECT * FROM active_items WHERE id=?",(item_id,)).fetchone()) for item_id in ids]})


def archive_active(db, row, stamp):
    if row["archive_policy"] != "episode" or row["archived_episode_id"]: return None
    eid=ident("ep"); occurred=row["starts_at"] or row["due_at"] or stamp
    db.execute("INSERT INTO episodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
      (eid,occurred,row["title"],row["summary"] or row["title"],None,None,row["status"],
       row["importance"],row["source_kind"],row["source_ref"],None,stamp,stamp))
    db.execute("UPDATE active_items SET archived_episode_id=? WHERE id=?",(eid,row["id"])); return eid


def cmd_active_set(db, a):
    if a.status not in ACTIVE_STATUS: raise SystemExit("invalid active status")
    stamp=now(); ids=a.ids or ([a.id] if a.id else [])
    if not ids: raise SystemExit("provide --id or --ids")
    rows={r["id"]:r for r in db.execute(f"SELECT * FROM active_items WHERE id IN ({','.join('?' for _ in ids)})",ids)}
    missing=[item_id for item_id in ids if item_id not in rows]
    if missing: raise SystemExit(f"active item not found: {', '.join(missing)}")
    terminal = a.status in ("completed","cancelled","missed")
    results=[]
    for item_id in ids:
        row=rows[item_id]
        if terminal and row["archive_policy"] == "discard":
            db.execute("DELETE FROM active_items WHERE id=?",(item_id,))
            audit(db,"discard_active_item","active_item",item_id,reason=a.reason,
                  details={"terminal_status":a.status})
            results.append({"id":item_id,"status":a.status,"discarded":True,"archived_episode_id":None})
            continue
        # A terminal transition also invalidates any not-yet-sent derived check-in.
        if terminal:
            db.execute("UPDATE active_items SET status=?,checkin_at=NULL,checkin_reason=NULL,updated_at=? WHERE id=?",(a.status,stamp,item_id))
        else:
            db.execute("UPDATE active_items SET status=?,updated_at=? WHERE id=?",(a.status,stamp,item_id))
        episode=archive_active(db,dict(row)|{"status":a.status},stamp) if terminal else None
        audit(db,"transition_active_item","active_item",item_id,reason=a.reason,details={"from":row["status"],"to":a.status,"episode":episode,"checkin_cancelled":terminal})
        results.append({"id":item_id,"status":a.status,"archived_episode_id":episode,"checkin_cancelled":terminal})
    db.commit(); emit({"items":results})

def cmd_active_checkin(db, a):
    stamp=now(); row=db.execute("SELECT id FROM active_items WHERE id=?",(a.id,)).fetchone()
    if not row: raise SystemExit("active item not found")
    db.execute("UPDATE active_items SET checkin_at=?,checkin_reason=?,updated_at=? WHERE id=?",(a.at,a.reason,stamp,a.id))
    audit(db,"schedule_active_checkin","active_item",a.id,reason=a.reason,details={"checkin_at":a.at})
    db.commit(); emit(dict(db.execute("SELECT * FROM active_items WHERE id=?",(a.id,)).fetchone()))

def cmd_active_notified(db, a):
    stamp=now(); ids=a.ids or ([a.id] if a.id else [])
    if not ids: raise SystemExit("provide --id or --ids")
    found={r["id"] for r in db.execute(f"SELECT id FROM active_items WHERE id IN ({','.join('?' for _ in ids)})",ids)}
    missing=[item_id for item_id in ids if item_id not in found]
    if missing: raise SystemExit(f"active item not found: {', '.join(missing)}")
    for item_id in ids:
        db.execute("UPDATE active_items SET checkin_sent_at=?,updated_at=? WHERE id=?",(stamp,stamp,item_id))
        audit(db,"send_active_checkin","active_item",item_id,details={"sent_at":stamp,"batch_size":len(ids)})
    db.commit(); emit({"ids":ids,"checkin_sent_at":stamp})


def cmd_active_tick(db, a):
    current=parse_time(a.at) or dt.datetime.now(dt.timezone.utc); stamp=now(); changes=[]
    for row in db.execute("SELECT * FROM active_items WHERE status IN ('tentative','scheduled','imminent')"):
        r=dict(row); target=parse_time(r["checkin_at"] or r["ends_at"] or r["starts_at"] or r["due_at"] or r["review_at"])
        if not target: continue
        delta=(target-current).total_seconds()
        new="awaiting_confirmation" if delta < 0 else ("imminent" if delta <= a.imminent_hours*3600 else ("scheduled" if r["status"]=="imminent" else r["status"]))
        if new != r["status"]:
            db.execute("UPDATE active_items SET status=?,updated_at=? WHERE id=?",(new,stamp,r["id"])); changes.append({"id":r["id"],"from":r["status"],"to":new})
            audit(db,"lifecycle_active_item","active_item",r["id"],details=changes[-1])
    db.commit(); emit({"at":current.isoformat(),"changes":changes})


def cmd_stats(db, _):
    tables=("entities","relationships","assertions","episodes","episode_entities","documents","reminders","active_items","audit_log")
    emit({t:db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables})


def sync_active_memory(db, db_path):
    """Publish compact current state for native memory search as a fallback/index layer."""
    rows = [dict(r) for r in db.execute(
        "SELECT * FROM active_items WHERE status NOT IN ('completed','cancelled','missed','deleted') "
        "ORDER BY coalesce(starts_at,due_at,review_at,created_at), importance DESC"
    )]
    target = db_path.parent.parent / "ACTIVE_STATE.md"
    lines = [
        "# Active State",
        "",
        "Generated from the structured active-state database. The database is authoritative; do not edit this file manually.",
        "",
    ]
    if not rows:
        lines.append("No current active items.")
    for row in rows:
        lines.extend([
            f"## {row['title']}",
            "",
            f"- ID: {row['id']}",
            f"- Kind: {row['kind']}",
            f"- Status: {row['status']}",
        ])
        if row["summary"]: lines.append(f"- Summary: {row['summary']}")
        if row["starts_at"]: lines.append(f"- Starts: {row['starts_at']}")
        if row["ends_at"]: lines.append(f"- Ends: {row['ends_at']}")
        if row["due_at"]: lines.append(f"- Due: {row['due_at']}")
        if row["review_at"]: lines.append(f"- Review: {row['review_at']}")
        if row["source_kind"]: lines.append(f"- Source kind: {row['source_kind']}")
        if row["source_ref"]: lines.append(f"- Source: {row['source_ref']}")
        lines.append("")
    temporary = target.with_suffix(".md.tmp")
    temporary.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    temporary.replace(target)


def parser():
    p=argparse.ArgumentParser(); p.add_argument("--db",type=Path,default=DEFAULT_DB); sub=p.add_subparsers(dest="cmd",required=True)
    sub.add_parser("init")
    e=sub.add_parser("entity"); e.add_argument("--type",required=True); e.add_argument("--name",required=True); e.add_argument("--alias",action="append"); e.add_argument("--description"); e.add_argument("--status",choices=VALID_STATUS,default="confirmed"); e.add_argument("--confidence",type=float,default=.9); e.add_argument("--source-kind",default="user_statement"); e.add_argument("--source-ref")
    r=sub.add_parser("relate"); r.add_argument("--subject",required=True); r.add_argument("--predicate",required=True); r.add_argument("--object",required=True); add_meta(r)
    m=sub.add_parser("remember"); m.add_argument("--subject",required=True); m.add_argument("--predicate",required=True); m.add_argument("--value",required=True); m.add_argument("--json",action="store_true"); m.add_argument("--category"); add_meta(m)
    s=sub.add_parser("supersede"); s.add_argument("--old-id",required=True); s.add_argument("--value",required=True); s.add_argument("--json",action="store_true"); s.add_argument("--reason",required=True); add_meta(s)
    c=sub.add_parser("correct"); c.add_argument("--old-id",required=True); c.add_argument("--value",required=True); c.add_argument("--json",action="store_true"); c.add_argument("--reason",required=True); add_meta(c)
    ep=sub.add_parser("episode"); ep.add_argument("--occurred-at",required=True); ep.add_argument("--topic",required=True); ep.add_argument("--summary",required=True); ep.add_argument("--decision"); ep.add_argument("--concerns"); ep.add_argument("--outcome"); ep.add_argument("--entity",action="append"); ep.add_argument("--importance",type=score,default=.6); ep.add_argument("--source-kind",default="discord"); ep.add_argument("--source-ref"); ep.add_argument("--markdown-path")
    f=sub.add_parser("forget"); f.add_argument("--record-id"); f.add_argument("--entity"); f.add_argument("--reason",required=True); f.add_argument("--source-ref")
    q=sub.add_parser("search"); q.add_argument("--query",required=True); q.add_argument("--historical",action="store_true"); q.add_argument("--limit",type=int,default=8)
    h=sub.add_parser("history"); h.add_argument("--entity",required=True)
    a=sub.add_parser("audit"); a.add_argument("--record-id"); a.add_argument("--limit",type=int,default=50)
    aa=sub.add_parser("active-add"); aa.add_argument("--kind",required=True); aa.add_argument("--title",required=True); aa.add_argument("--summary"); aa.add_argument("--status",choices=ACTIVE_STATUS,default="tentative"); aa.add_argument("--starts-at"); aa.add_argument("--due-at"); aa.add_argument("--ends-at"); aa.add_argument("--review-at"); aa.add_argument("--checkin-at"); aa.add_argument("--checkin-reason"); aa.add_argument("--importance",type=score,default=.6); aa.add_argument("--confidence",type=score,default=.9); aa.add_argument("--source-kind",default="user_statement"); aa.add_argument("--source-ref"); aa.add_argument("--entity",action="append"); aa.add_argument("--topic",action="append"); aa.add_argument("--archive-policy",choices=("episode","retain","discard"),default="episode")
    al=sub.add_parser("active-list"); al.add_argument("--query"); al.add_argument("--kind"); al.add_argument("--future-only",action="store_true"); al.add_argument("--historical",action="store_true"); al.add_argument("--at"); al.add_argument("--limit",type=int,default=8)
    au=sub.add_parser("active-update"); au.add_argument("--id"); au.add_argument("--ids",nargs="+"); au.add_argument("--reason",required=True); au.add_argument("--title"); au.add_argument("--summary"); au.add_argument("--starts-at"); au.add_argument("--due-at"); au.add_argument("--ends-at"); au.add_argument("--review-at"); au.add_argument("--checkin-at"); au.add_argument("--checkin-reason")
    aset=sub.add_parser("active-set"); aset.add_argument("--id"); aset.add_argument("--ids",nargs="+"); aset.add_argument("--status",required=True,choices=ACTIVE_STATUS); aset.add_argument("--reason",required=True)
    ac=sub.add_parser("active-checkin"); ac.add_argument("--id",required=True); ac.add_argument("--at",required=True); ac.add_argument("--reason",required=True)
    an=sub.add_parser("active-notified"); an.add_argument("--id"); an.add_argument("--ids",nargs="+")
    tick=sub.add_parser("active-tick"); tick.add_argument("--at"); tick.add_argument("--imminent-hours",type=int,default=72)
    sub.add_parser("stats")
    return p


def add_meta(p):
    p.add_argument("--status",choices=VALID_STATUS,default="confirmed"); p.add_argument("--confidence",type=score,default=.9); p.add_argument("--importance",type=score,default=.6); p.add_argument("--valid-from"); p.add_argument("--valid-to"); p.add_argument("--source-kind",default="user_statement"); p.add_argument("--source-ref")


def main():
    a=parser().parse_args(); db=connect(a.db); db.executescript(SCHEMA); migrate(db)
    fn={"init":cmd_init,"entity":cmd_entity,"relate":cmd_relate,"remember":cmd_remember,"supersede":cmd_supersede,"correct":cmd_supersede,"episode":cmd_episode,"forget":cmd_forget,"search":cmd_search,"history":cmd_history,"audit":cmd_audit,"active-add":cmd_active_add,"active-list":cmd_active_list,"active-update":cmd_active_update,"active-set":cmd_active_set,"active-checkin":cmd_active_checkin,"active-notified":cmd_active_notified,"active-tick":cmd_active_tick,"stats":cmd_stats}[a.cmd]
    try:
        fn(db,a)
        if a.cmd in {"init", "active-add", "active-update", "active-set", "active-checkin", "active-notified", "active-tick"}:
            sync_active_memory(db, a.db)
    except sqlite3.IntegrityError as exc: raise SystemExit(f"integrity error: {exc}")


if __name__ == "__main__": main()
