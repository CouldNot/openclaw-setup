#!/usr/bin/env python3
import json, sqlite3, subprocess, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "workspace/skills/second-brain/scripts/second_brain.py"


class SecondBrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.sqlite"
        self.cli("init")

    def tearDown(self): self.tmp.cleanup()

    def cli(self, *args):
        out = subprocess.check_output(["python3", str(SCRIPT), "--db", str(self.db), *args], text=True)
        return json.loads(out)

    def entity(self, typ, name): return self.cli("entity", "--type", typ, "--name", name)["id"]

    def test_durable_fact_and_relationship(self):
        self.entity("PERSON", "Jordan"); self.entity("PROJECT", "Project A")
        self.cli("relate", "--subject", "Jordan", "--predicate", "helps_with", "--object", "Project A")
        result = self.cli("search", "--query", "Jordan")
        self.assertEqual(result["relationships"][0]["object_name"], "Project A")

    def test_tentative_then_confirmed_supersession(self):
        self.entity("COURSE", "Course A")
        old = self.cli("remember", "--subject", "Course A", "--predicate", "enrollment", "--value", "considering", "--status", "tentative")
        new = self.cli("supersede", "--old-id", old["id"], "--value", "enrolled", "--reason", "User confirmed enrollment")
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("select status from assertions where id=?", (old["id"],)).fetchone()[0], "superseded")
            self.assertEqual(db.execute("select supersedes_id from assertions where id=?", (new["id"],)).fetchone()[0], old["id"])

    def test_history_preserved(self):
        self.entity("PLACE", "Chicago")
        old = self.cli("remember", "--subject", "user", "--predicate", "planned_location", "--value", "Chicago")
        self.cli("supersede", "--old-id", old["id"], "--value", "Vancouver", "--reason", "Changed mind")
        history = self.cli("history", "--entity", "user")
        self.assertEqual(len(history["assertions"]), 2)

    def test_forgetting_hides_assertion(self):
        self.entity("PERSON", "Alex")
        fact = self.cli("remember", "--subject", "Alex", "--predicate", "relationship", "--value", "roommate")
        self.cli("forget", "--record-id", fact["id"], "--reason", "User requested deletion")
        self.assertEqual(self.cli("search", "--query", "roommate")["assertions"], [])

    def test_same_name_entities_do_not_merge_across_types(self):
        person = self.entity("PERSON", "Phoenix")
        project = self.entity("PROJECT", "Phoenix")
        self.assertNotEqual(person, project)

    def test_active_lifecycle_and_archive(self):
        item = self.cli("active-add", "--kind", "appointment", "--title", "Move-in",
                        "--status", "scheduled", "--starts-at", "2026-08-19T11:00:00-07:00")
        tick = self.cli("active-tick", "--at", "2026-08-18T12:00:00-07:00")
        self.assertEqual(tick["changes"][0]["to"], "imminent")
        done = self.cli("active-set", "--id", item["id"], "--status", "completed", "--reason", "Occurred")["items"][0]
        self.assertTrue(done["archived_episode_id"])
        self.assertEqual(self.cli("active-list")["items"], [])
        self.assertEqual(self.cli("active-list", "--historical")["items"][0]["status"], "completed")

    def test_active_temporal_ranking(self):
        self.cli("active-add", "--kind", "task", "--title", "Later", "--status", "scheduled", "--due-at", "2026-10-01T00:00:00+00:00")
        self.cli("active-add", "--kind", "appointment", "--title", "Soon", "--status", "scheduled", "--starts-at", "2026-08-13T00:00:00+00:00")
        rows=self.cli("active-list", "--at", "2026-08-12T00:00:00+00:00")["items"]
        self.assertEqual(rows[0]["title"], "Soon")

    def test_human_friendly_importance_labels(self):
        item = self.cli("active-add", "--kind", "task", "--title", "Buy supplies",
                        "--importance", "normal", "--confidence", "high")
        self.assertEqual(item["importance"], 0.5)
        self.assertEqual(item["confidence"], 0.75)

    def test_past_event_awaits_confirmation(self):
        self.cli("active-add", "--kind", "appointment", "--title", "Dentist",
                 "--status", "scheduled", "--starts-at", "2026-08-10T10:00:00+00:00")
        tick=self.cli("active-tick", "--at", "2026-08-12T00:00:00+00:00")
        self.assertEqual(tick["changes"][0]["to"], "awaiting_confirmation")

    def test_contextual_default_checkin_times(self):
        med=self.cli("active-add", "--kind", "medication", "--title", "Take medication", "--starts-at", "2026-08-12T10:00:00+00:00")
        move=self.cli("active-add", "--kind", "appointment", "--title", "University move-in", "--starts-at", "2026-08-12T10:00:00+00:00")
        buy=self.cli("active-add", "--kind", "task", "--title", "Buy a laptop", "--due-at", "2026-08-12T10:00:00+00:00")
        self.assertEqual(med["checkin_at"], "2026-08-12T10:15:00+00:00")
        self.assertEqual(move["checkin_at"], "2026-08-12T15:00:00+00:00")
        self.assertEqual(buy["checkin_at"], "2026-08-12T13:00:00+00:00")

    def test_explicit_llm_checkin_overrides_fallback(self):
        item=self.cli("active-add", "--kind", "appointment", "--title", "Long event", "--starts-at", "2026-08-12T10:00:00+00:00", "--checkin-at", "2026-08-12T20:00:00+00:00", "--checkin-reason", "Event may take most of the day")
        self.assertEqual(item["checkin_at"], "2026-08-12T20:00:00+00:00")

    def test_discard_physically_removes_item_without_content_in_audit(self):
        item=self.cli("active-add", "--kind", "medication", "--title", "Sensitive trivial detail", "--archive-policy", "discard")
        result=self.cli("active-set", "--id", item["id"], "--status", "completed", "--reason", "User confirmed it")["items"][0]
        self.assertTrue(result["discarded"])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("select count(*) from active_items where id=?", (item["id"],)).fetchone()[0], 0)
            audit=json.loads(db.execute("select details_json from audit_log where action='discard_active_item' and record_id=?", (item["id"],)).fetchone()[0])
            self.assertNotIn("Sensitive trivial detail", json.dumps(audit))

    def test_retain_keeps_structured_record_without_episode(self):
        item=self.cli("active-add", "--kind", "task", "--title", "Routine admin", "--archive-policy", "retain")
        result=self.cli("active-set", "--id", item["id"], "--status", "completed", "--reason", "Done")["items"][0]
        self.assertIsNone(result["archived_episode_id"])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("select status from active_items where id=?", (item["id"],)).fetchone()[0], "completed")
            self.assertEqual(db.execute("select count(*) from episodes").fetchone()[0], 0)

if __name__ == "__main__": unittest.main()
