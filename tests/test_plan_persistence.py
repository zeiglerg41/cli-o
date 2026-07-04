"""Unit tests for per-conversation plan persistence."""

import json

from clio.history.database import HistoryDatabase


def make_db(tmp_path):
    return HistoryDatabase(db_path=tmp_path / "test.db")


class TestPlanPersistence:
    def test_save_and_get_roundtrip(self, tmp_path):
        db = make_db(tmp_path)
        cid = db.create_conversation("/tmp", "m", "p")
        plan = {"explanation": "", "plan": [{"step": "a", "status": "in_progress"}]}
        db.save_plan(cid, json.dumps(plan))
        assert json.loads(db.get_plan(cid)) == plan
        db.close()

    def test_get_plan_none_when_unset(self, tmp_path):
        db = make_db(tmp_path)
        cid = db.create_conversation("/tmp", "m", "p")
        assert db.get_plan(cid) is None
        db.close()

    def test_save_overwrites(self, tmp_path):
        db = make_db(tmp_path)
        cid = db.create_conversation("/tmp", "m", "p")
        db.save_plan(cid, json.dumps({"plan": [{"step": "old", "status": "pending"}]}))
        db.save_plan(cid, json.dumps({"plan": [{"step": "new", "status": "completed"}]}))
        assert "new" in db.get_plan(cid)
        db.close()

    def test_migration_on_existing_db(self, tmp_path):
        # Opening twice must not fail on the ALTER TABLE migration
        db = make_db(tmp_path)
        db.close()
        db = make_db(tmp_path)
        cid = db.create_conversation("/tmp", "m", "p")
        db.save_plan(cid, "{}")
        db.close()
