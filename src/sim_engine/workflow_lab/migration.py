"""Evidence-bound migration stages for a fixture authoring gateway."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sim_engine.evidence import digest

from .compiler import artifact_digest
from .contracts import Evidence, Result


def load_evidence(path: Path) -> Evidence:
    report = Evidence.model_validate_json(path.read_text(encoding="utf-8"))
    manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
    rows = [Result.model_validate_json(line) for line in (path.parent / "outcomes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if report.artifacts_digest != digest([r.model_dump() for r in rows]):
        raise ValueError("Evidence outcome digest mismatch")
    if report.release != manifest["release"] or report.dataset_digest != manifest["dataset_digest"] or report.executor != manifest["executor"]:
        raise ValueError("Evidence does not match its run manifest")
    old, new = [r for r in rows if r.variant == "baseline"], [r for r in rows if r.variant == "candidate"]
    if (report.observations != len(rows) or report.candidate_observations != len(new) or
            report.baseline_observations != len(old) or report.candidate_failures != sum(not r.success for r in new) or
            report.baseline_failures != sum(not r.success for r in old) or
            report.coverage != sorted({r.cohort for r in new})):
        raise ValueError("Evidence counts do not match recorded outcomes")
    expected_pass = all(r.artifact_digest for r in old) and bool(old) if report.stage == "baseline" else bool(new) and all(r.success for r in new)
    if report.passed != expected_pass:
        raise ValueError("Evidence pass status disagrees with outcomes")
    latency = sum(r.latency_ms for r in new) / len(new) if new else 0
    cost = sum(r.estimated_cost_usd for r in new) / len(new) if new and all(r.estimated_cost_usd is not None for r in new) else None
    if report.candidate_mean_latency_ms != latency or report.candidate_mean_cost_usd != cost:
        raise ValueError("Evidence latency/cost does not match outcomes")
    for row in rows:
        if row.artifact_digest:
            workflow = json.loads((path.parent / "episodes" / row.task_id / row.variant / "workflow.json").read_text(encoding="utf-8"))
            if artifact_digest(workflow) != row.artifact_digest:
                raise ValueError("Evaluated workflow artifact has changed")
    return report


class Migration:
    def __init__(self, database: Path):
        database.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database, timeout=30)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS migration_settings (id INTEGER PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS migration_audit (at TEXT, operation TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS migration_used (stage TEXT, window TEXT, PRIMARY KEY(stage,window));
            CREATE TABLE IF NOT EXISTS creator_assignments (tenant TEXT, session TEXT, arm TEXT, PRIMARY KEY(tenant,session));
        """)

    def close(self):
        self.db.close()

    def _audit(self, operation, data):
        self.db.execute("INSERT INTO migration_audit VALUES (?,?,?)", (datetime.now(timezone.utc).isoformat(), operation, json.dumps(data)))

    def status(self):
        row = self.db.execute("SELECT value FROM migration_settings WHERE id=1").fetchone()
        if row is None:
            raise ValueError("Initialize this controller first")
        return json.loads(row[0])

    def _save(self, state):
        self.db.execute("UPDATE migration_settings SET value=? WHERE id=1", (json.dumps(state),))

    def initialize(self, release, executor, salt="incident-creator-v1", minimum=5, max_latency_ms=60000, max_cost_usd=None):
        if executor not in ("reference", "n8n") or minimum < 1 or max_latency_ms <= 0 or (max_cost_usd is not None and max_cost_usd < 0):
            raise ValueError("Invalid controller configuration")
        value = {"release": release, "executor": executor, "scope": "fixture", "phase": "baseline",
                 "percent": 0, "paused": False, "salt": salt, "minimum_candidate_observations": minimum,
                 "max_latency_ms": max_latency_ms, "max_cost_usd": max_cost_usd,
                 "production_authorized": False}
        with self.db:
            self.db.execute("INSERT INTO migration_settings VALUES(1,?)", (json.dumps(value),))
            self._audit("initialize", value)
        return value

    def _validate(self, state: dict, evidence: Evidence):
        if evidence.release != state["release"] or evidence.executor != state["executor"] or evidence.scope != state["scope"]:
            raise ValueError("Evidence release/runtime/scope does not match the controller")
        at = datetime.fromisoformat(evidence.observed_at)
        if at.tzinfo is None or not -60 <= (datetime.now(timezone.utc) - at).total_seconds() <= 86400:
            raise ValueError("Evidence is stale or has an invalid timestamp")
        if evidence.observations < 1:
            raise ValueError("Evidence has no observations")

    def advance(self, target: str, evidence: Evidence, percent: float | None = None):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            state = self.status()
            if state["paused"]:
                raise ValueError("Rollback is latched; investigate and initialize a new experiment")
            self._validate(state, evidence)
            required = {("baseline", "offline"): "baseline", ("offline", "shadow"): "offline",
                        ("shadow", "canary"): "shadow", ("canary", "expansion"): "canary",
                        ("expansion", "expansion"): "canary", ("expansion", "full"): "canary"}
            expected = required.get((state["phase"], target))
            if expected is None or evidence.stage != expected:
                raise ValueError("Cannot skip a migration stage or use the wrong evidence kind")
            if not evidence.passed:
                raise ValueError("Evidence did not pass")
            if expected != "baseline":
                if evidence.candidate_failures or evidence.candidate_observations < state["minimum_candidate_observations"]:
                    raise ValueError("Candidate failures or insufficient observations")
                if len(evidence.coverage) < 4:
                    raise ValueError("The four declared creator cohorts must be covered")
                if expected in ("offline", "shadow") and evidence.baseline_observations != evidence.candidate_observations:
                    raise ValueError("Paired evidence is required before canary")
                if evidence.candidate_mean_latency_ms > state["max_latency_ms"]:
                    raise ValueError("Candidate latency exceeds the configured limit")
                limit = state["max_cost_usd"]
                if limit is not None and (evidence.candidate_mean_cost_usd is None or evidence.candidate_mean_cost_usd > limit):
                    raise ValueError("Candidate cost is unknown or exceeds the configured limit")
            exposure = 100.0 if target == "full" else (percent if percent is not None else (5.0 if target == "canary" else state["percent"]))
            if target in ("canary", "expansion", "full"):
                if not state["percent"] < exposure <= 100 or (target != "full" and exposure == 100):
                    raise ValueError("Exposure must increase; only full migration may reach 100%")
            elif exposure != 0:
                raise ValueError("Live assignments must stay at zero before canary")
            self.db.execute("INSERT INTO migration_used VALUES (?,?)", ("promote-" + expected, evidence.window))
            state.update(phase=target, percent=exposure)
            self._save(state)
            self._audit("advance", {"state": state, "evidence_id": evidence.evidence_id,
                "window": evidence.window, "artifacts_digest": evidence.artifacts_digest})
        return state

    def route(self, tenant: str, session: str):
        if not tenant or not session:
            raise ValueError("Tenant and session are required")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            state = self.status()
            old = self.db.execute("SELECT arm FROM creator_assignments WHERE tenant=? AND session=?", (tenant, session)).fetchone()
            if state["paused"]:
                arm = "drain" if old and old[0] == "candidate" else "baseline"
            elif old:
                arm = old[0]
            else:
                key = (state["release"] + ":" + state["salt"] + ":" + tenant).encode()
                fraction = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") / 2**64
                arm = "candidate" if fraction * 100 < state["percent"] else "baseline"
            if arm != "drain":
                self.db.execute("INSERT OR IGNORE INTO creator_assignments VALUES (?,?,?)", (tenant, session, arm))
            result = {"arm": arm, "tenant": tenant, "session": session, "phase": state["phase"],
                      "executor": state["executor"], "scope": "fixture", "production_authorized": False}
            self._audit("route", result)
        return result

    def rollback(self, reason: str):
        if not reason.strip():
            raise ValueError("Rollback requires a reason")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            state = self.status()
            state.update(phase="rollback", percent=0, paused=True)
            self._save(state)
            self._audit("rollback", {"reason": reason, "state": state})
        return state

    def observe(self, evidence: Evidence):
        # Commit receipt first, then invoke rollback in a separate transaction.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            state = self.status()
            self._validate(state, evidence)
            if evidence.stage != "canary" or state["phase"] not in ("canary", "expansion", "full"):
                raise ValueError("Monitoring requires assigned canary observations in an active stage")
            self.db.execute("INSERT INTO migration_used VALUES (?,?)", ("observe", evidence.window))
            self._audit("observe", evidence.model_dump())
        limit = state["max_cost_usd"]
        if (evidence.candidate_failures or evidence.candidate_mean_latency_ms > state["max_latency_ms"] or
                (limit is not None and (evidence.candidate_mean_cost_usd is None or evidence.candidate_mean_cost_usd > limit))):
            return self.rollback("Candidate workflow failed quality, latency, or configured cost checks")
        return self.status()
