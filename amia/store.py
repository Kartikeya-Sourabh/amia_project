"""SQLite audit store. The original verified report is never modified; human corrections are appended
with a before/after snapshot, reviewer, note and timestamp."""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from . import patterns as P
from .dates import find_dates, parse_one

ACTIONS = {"confirm": "confirmed", "edit": "corrected", "reject": "rejected"}


class ValidationError(ValueError):
    pass


class Store:
    def __init__(self, path):
        self.path, self.lock = path, threading.Lock()
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at TEXT, title TEXT,
                    meeting_date TEXT, engine TEXT, report_json TEXT);
                CREATE TABLE IF NOT EXISTS corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT,
                    item_id TEXT, created_at TEXT, reviewer TEXT, note TEXT, action TEXT,
                    before_json TEXT, after_json TEXT);""")

    def _db(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def create_run(self, report):
        rid = uuid.uuid4().hex[:10]
        report["id"] = rid
        with self.lock, self._db() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                       (rid, _now(), report["title"], report["meeting_date"], report["engine_used"],
                        json.dumps(report)))
        return self.get_run(rid)

    def list_runs(self):
        with self._db() as db:
            rows = db.execute("SELECT id, created_at, title, meeting_date, engine FROM runs "
                              "ORDER BY created_at DESC LIMIT 100").fetchall()
        return [dict(r) for r in rows]

    def get_run(self, rid):
        with self._db() as db:
            row = db.execute("SELECT report_json FROM runs WHERE id=?", (rid,)).fetchone()
            if not row:
                return None
            corr = db.execute("SELECT * FROM corrections WHERE run_id=? ORDER BY id", (rid,)).fetchall()
        report = json.loads(row["report_json"])
        by_item = {}
        for c in corr:
            by_item.setdefault(c["item_id"], []).append({
                "id": c["id"], "at": c["created_at"], "reviewer": c["reviewer"], "note": c["note"],
                "action": c["action"], "before": json.loads(c["before_json"]), "after": json.loads(c["after_json"])})
        for it in report["items"]:
            cur = {"type": it["type"], "summary": it["summary"], "owner": it["owner"],
                   "due": it["due"]["iso"] or it["due"]["raw"], "review": None}
            hist = by_item.get(it["id"], [])
            for h in hist:
                cur.update(h["after"])
            it["current"], it["history"] = cur, hist
        return report

    def add_correction(self, rid, item_id, payload):
        report = self.get_run(rid)
        if not report:
            raise KeyError("run not found")
        item = next((i for i in report["items"] if i["id"] == item_id), None)
        if not item:
            raise KeyError("item not found")
        action = payload.get("action")
        if action not in ACTIONS:
            raise ValidationError("action must be confirm, edit or reject")
        before = dict(item["current"])
        after = {"review": ACTIONS[action]}
        if action == "edit":
            for k in ("type", "summary", "owner", "due"):
                if k not in payload:
                    continue
                v = payload[k]
                v = v.strip() if isinstance(v, str) else v
                if k == "type" and v not in P.TYPES:
                    raise ValidationError(f"type must be one of {P.TYPES}")
                if k == "summary" and not v:
                    raise ValidationError("summary cannot be empty")
                if k == "due" and v:
                    iso = parse_one(v, _ref(report))
                    if not iso:
                        raise ValidationError("due must be a clear date, e.g. 2026-11-18 or '18 November'")
                    v = iso
                if v != before.get(k) and not (v in ("", None) and before.get(k) in ("", None)):
                    after[k] = v or None
            if len(after) == 1:
                raise ValidationError("edit contains no changes")
        with self.lock, self._db() as db:
            db.execute("INSERT INTO corrections (run_id,item_id,created_at,reviewer,note,action,before_json,after_json)"
                       " VALUES (?,?,?,?,?,?,?,?)",
                       (rid, item_id, _now(), (payload.get("reviewer") or "anonymous")[:80],
                        (payload.get("note") or "")[:500], action, json.dumps(before), json.dumps(after)))
        return self.get_run(rid)


def _ref(report):
    from datetime import date
    return date.fromisoformat(report["meeting_date"])


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
