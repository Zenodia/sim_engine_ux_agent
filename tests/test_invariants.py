"""Focused boundary checks for manual execution on the remote machine."""
import asyncio
from pathlib import Path

import pytest

from sim_engine.agents import run_rules
from sim_engine.contracts import Persona, Scenario
from sim_engine.evaluation import verify
from sim_engine.evidence import Journal
from sim_engine.memory import Memory
from sim_engine.rollout import Rollout
from sim_engine.world import World


def scenario(**changes):
    fields = dict(
        scenario_id="development-example", seed=42, split="development", suite="stress", cohort="analyst",
        persona=Persona(user_id="u", tenant_id="t", role="analyst", locale="en", expertise="novice",
                        patience=4, initial_channel="chat"),
        requested_role="viewer", changed_preference=True, ambiguous_workspace=True,
        timeout_after_commit=True, revoked_access=False, tool_injection=True, stale_memory=True,
    )
    fields.update(changes)
    return Scenario(**fields)


def world(tmp_path, s):
    journal = Journal(tmp_path / "events.jsonl")
    memory = Memory(1, "t", "u", "isolated", journal)
    return World(s, memory, journal)


def test_write_timeout_retry_does_not_duplicate_mutation(tmp_path):
    w = world(tmp_path, scenario())
    w.start_session(2)
    args = {"workspace": "analytics", "role": "viewer", "idempotency_key": "k"}
    assert w.call("grant_access", args)["outcome"] == "unknown"
    assert w.call("grant_access", args)["granted"] is True
    assert len(w.grants) == 1
    assert w.call("grant_access", {**args, "role": "admin"})["error"] == "idempotency_conflict"


def test_enforcement_rejects_unauthorized_action(tmp_path):
    w = world(tmp_path, scenario(revoked_access=True))
    w.start_session(2)
    result = w.call("grant_access", {"workspace": "analytics", "role": "viewer", "idempotency_key": "k"})
    assert result["error"] == "policy_denied"
    assert w.grants == []
    assert len(w.denied_attempts) == 1


def test_migration_preserves_user_scope_and_fact_values(tmp_path):
    w = world(tmp_path, scenario())
    w.memory.write("notification_channel", "chat")
    new = w.memory.migrate(2)
    new.write("notification_channel", "email")
    restored = new.migrate(1)
    assert restored.scope == w.memory.scope
    assert restored.read("notification_channel") == "email"
    assert w.memory.read("notification_channel") == "chat"


def test_candidate_handles_combined_memory_policy_and_retry_stress(tmp_path):
    s = scenario()
    w = world(tmp_path, s)
    w.memory.write("workspace_role", "admin")
    for session in (1, 2):
        message = w.start_session(session)
        if session == 2:
            w.memory = w.memory.migrate(2)
        asyncio.run(run_rules(w, message, "candidate"))
    assert all(check.passed for check in verify(s, w))


def test_rollback_drains_existing_candidate_sessions(tmp_path):
    router = Rollout(tmp_path / "routes.sqlite")
    try:
        router.initialize("migration", "fixed-salt")
        with pytest.raises(ValueError):
            router.set_percent(100, {"decision": "hold"})
        router.set_percent(100, {"decision": "eligible_for_manual_review"})
        assert router.route("tenant", "existing")["arm"] == "candidate"
        router.rollback("quality regression")
        assert router.route("tenant", "existing")["arm"] == "drain"
        assert router.route("tenant", "new")["arm"] == "baseline"
        with pytest.raises(ValueError):
            router.set_percent(100, {"decision": "eligible_for_manual_review"})
    finally:
        router.close()
