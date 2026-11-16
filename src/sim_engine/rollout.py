import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Rollout:
    """Transactional local routing lab. It never changes a real gateway."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                experiment TEXT, tenant TEXT, session TEXT, arm TEXT,
                PRIMARY KEY (experiment, tenant, session));
            CREATE TABLE IF NOT EXISTS audit (at TEXT, operation TEXT, payload TEXT);
        """)

    def close(self) -> None:
        self.connection.close()

    def _audit(self, operation: str, payload: dict) -> None:
        self.connection.execute("INSERT INTO audit VALUES (?, ?, ?)",
                                (datetime.now(timezone.utc).isoformat(), operation, json.dumps(payload)))

    def _settings(self) -> dict:
        row = self.connection.execute("SELECT payload FROM settings WHERE id=1").fetchone()
        if row is None:
            raise ValueError("Initialize the experiment first")
        return json.loads(row[0])

    def initialize(self, experiment: str, salt: str) -> dict:
        if not experiment or not salt:
            raise ValueError("Experiment and salt must be nonempty")
        result = {"experiment": experiment, "salt": salt, "percent": 0.0, "paused": False}
        with self.connection:
            self.connection.execute("INSERT INTO settings VALUES (1, ?)", (json.dumps(result),))
            self._audit("initialize", result)
        return result

    def set_percent(self, percent: float, evidence: dict) -> dict:
        if not 0 <= percent <= 100:
            raise ValueError("Percent must be between 0 and 100")
        if evidence.get("decision") != "eligible_for_manual_review":
            raise ValueError("A passing local gate is required; this does not authorize production rollout")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            result = self._settings()
            if result["paused"]:
                raise ValueError("Rollback is latched. Create a new experiment database after investigating")
            if percent < result["percent"]:
                raise ValueError("Use rollback to reduce exposure in this lab")
            result["percent"] = percent
            self.connection.execute("UPDATE settings SET payload=? WHERE id=1", (json.dumps(result),))
            self._audit("set_percent", {"settings": result, "evidence": evidence})
        return result

    def route(self, tenant: str, session: str) -> dict:
        if not tenant or not session:
            raise ValueError("Tenant and session must be nonempty")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            config = self._settings()
            existing = self.connection.execute(
                "SELECT arm FROM sessions WHERE experiment=? AND tenant=? AND session=?",
                (config["experiment"], tenant, session)).fetchone()
            if config["paused"]:
                # Never silently change an in-flight candidate session's state schema.
                arm = "drain" if existing and existing[0] == "candidate" else "baseline"
            elif existing:
                arm = existing[0]
            else:
                key = f"{config['experiment']}:{config['salt']}:{tenant}".encode()
                bucket = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") / 2**64
                arm = "candidate" if bucket * 100 < config["percent"] else "baseline"
            if arm != "drain":
                self.connection.execute("INSERT OR IGNORE INTO sessions VALUES (?, ?, ?, ?)",
                                        (config["experiment"], tenant, session, arm))
            result = {"arm": arm, "tenant": tenant, "session": session,
                      "memory_schema": {"baseline": 1, "candidate": 2}.get(arm),
                      "note": "Local assignment only; no external agent execution or traffic routing."}
            self._audit("route", result)
        return result

    def rollback(self, reason: str) -> dict:
        if not reason.strip():
            raise ValueError("Rollback reason is required")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            result = self._settings()
            result.update(percent=0.0, paused=True)
            self.connection.execute("UPDATE settings SET payload=? WHERE id=1", (json.dumps(result),))
            self._audit("rollback", {"reason": reason, "settings": result})
        return result
