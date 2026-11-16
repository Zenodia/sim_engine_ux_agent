"""Regression coverage for provider output shapes seen during live verification."""
import json
from pathlib import Path

import pytest

from scripts.generate_sdg import parse_batch
from sim_engine.scenarios import load_scenarios
from sim_engine.world import UserSimulator


def test_sdg_accepts_unchanged_echoed_annotations():
    source = load_scenarios(Path("examples/one-scenario.jsonl"))[0]
    simulator = UserSimulator(source)
    payload = {"users": [{"scenario_id": source.scenario_id,
                         "session1": simulator.initial_message(1),
                         "session2": simulator.initial_message(2),
                         "locale": source.persona.locale, "expertise": source.persona.expertise}]}
    assert parse_batch(json.dumps(payload), [source])[source.scenario_id]["1"] == simulator.initial_message(1)
    payload["users"][0]["locale"] = "different-locale"
    with pytest.raises(ValueError, match="locale"):
        parse_batch(json.dumps(payload), [source])


def test_sdg_rejects_changed_permission_tokens():
    source = load_scenarios(Path("examples/one-scenario.jsonl"))[0]
    simulator = UserSimulator(source)
    payload = {"users": [{"scenario_id": source.scenario_id,
                         "session1": simulator.initial_message(1),
                         "session2": simulator.initial_message(2).replace("viewer", "admin")}]}
    with pytest.raises(ValueError, match="task tokens"):
        parse_batch(json.dumps(payload), [source])
