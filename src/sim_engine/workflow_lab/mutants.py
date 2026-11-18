"""Deliberate workflow defects ("mutants") used to measure how good the verifier and a test suite are.

A good suite should *kill* every applicable mutant: the independent final-effect oracle
(`evaluate.verify_effects`) must report at least one failed check. Spec mutants change the
authored requirements (what a faulty creator might produce); engine mutants change the compiled
workflow (what a faulty compiler might produce). Both execute on the reference and real n8n runtimes.
"""
from dataclasses import dataclass
from typing import Callable

import re

from .compiler import TITLE_TRIGGER_PATTERN
from .contracts import Spec

SEVERITIES = ["low", "medium", "high", "critical"]


def _shift(spec: Spec, delta: int) -> Spec:
    i = min(max(SEVERITIES.index(spec.minimum_severity) + delta, 0), len(SEVERITIES) - 1)
    return spec.model_copy(update={"minimum_severity": SEVERITIES[i]})


@dataclass(frozen=True)
class Mutant:
    name: str
    description: str
    spec_fn: Callable[[Spec], Spec] = lambda spec: spec
    engine: str | None = None  # compiler/runtime-level mutation, see compiler.ENGINE_MUTATIONS

    def applicable(self, expected: Spec, events: list[dict], tenant: str, faults: dict) -> bool:
        """False for equivalent mutants (no observable change is possible), so they never count as survivors."""
        if self.engine == "no_retry":
            return bool(faults.get("ticket") or faults.get("notification"))
        if self.engine == "no_tenant_check":
            return any(e.get("tenant") != tenant for e in events)
        if self.engine == "title_routes":
            return any(re.search(TITLE_TRIGGER_PATTERN, str(e.get("title", "")), re.I) for e in events)
        return self.spec_fn(expected) != expected


MUTANTS: list[Mutant] = [
    Mutant("threshold_up", "minimum severity one step too high (drops at-threshold events)", lambda s: _shift(s, 1)),
    Mutant("threshold_down", "minimum severity one step too low (accepts below-threshold events)", lambda s: _shift(s, -1)),
    Mutant("eu_channel_is_default", "EU events routed to the default channel",
           lambda s: s.model_copy(update={"eu_channel": s.default_channel})),
    Mutant("ack_flipped", "acknowledgement rule inverted",
           lambda s: s.model_copy(update={"acknowledgement_before_escalation": not s.acknowledgement_before_escalation})),
    Mutant("pii_leak", "personal fields not removed", lambda s: s.model_copy(update={"minimize_personal_data": False})),
    Mutant("no_dedupe", "duplicate deliveries create duplicate effects", lambda s: s.model_copy(update={"deduplicate": False})),
    Mutant("no_retry", "HTTP nodes do not retry transient 503s", engine="no_retry"),
    Mutant("no_tenant_check", "events from another tenant are processed", engine="no_tenant_check"),
    Mutant("title_routes", "obeys instructions embedded in the alert title (routes to an external sink)", engine="title_routes"),
]
BY_NAME = {m.name: m for m in MUTANTS}
