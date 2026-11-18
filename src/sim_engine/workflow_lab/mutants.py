"""Deliberate workflow defects ("mutants") used to measure how good the verifier and a test suite are.

A good suite should *kill* every applicable mutant: the independent final-effect oracle
(`evaluate.verify_effects`) must report at least one failed check. Spec mutants change the
authored requirements (what a faulty creator might produce); engine mutants change the compiled
workflow (what a faulty compiler might produce). Both execute on the reference and real n8n runtimes.

`applicable` is false only when the suite's events cannot exercise the mutated behaviour at all
(or the mutant is equivalent to the original spec). A suite that never exercises a mutant is reported as a
coverage gap ("never exercised") by the certification report, not credited with a kill.
"""
import re
from dataclasses import dataclass
from typing import Callable

from .compiler import TITLE_DIRECTIVE_PATTERN
from .contracts import Spec

SEVERITIES = ["low", "medium", "high", "critical"]


def _shift(spec: Spec, delta: int) -> Spec:
    i = min(max(SEVERITIES.index(spec.minimum_severity) + delta, 0), len(SEVERITIES) - 1)
    return spec.model_copy(update={"minimum_severity": SEVERITIES[i]})


def accepted_events(expected: Spec, events: list[dict], tenant: str) -> list[dict]:
    """Events a correct workflow turns into effects (valid, own tenant, at or above the threshold)."""
    return [e for e in events if e.get("tenant") == tenant and isinstance(e.get("event_id"), str) and e["event_id"]
            and e.get("severity") in SEVERITIES and SEVERITIES.index(e["severity"]) >= SEVERITIES.index(expected.minimum_severity)
            and e.get("region") in ("EU", "US")]


@dataclass(frozen=True)
class Mutant:
    name: str
    description: str
    spec_fn: Callable[[Spec], Spec] = lambda spec: spec
    engine: str | None = None  # compiler/runtime-level mutation, see compiler.ENGINE_MUTATIONS

    def applicable(self, expected: Spec, events: list[dict], tenant: str, faults: dict) -> bool:
        accepted = accepted_events(expected, events, tenant)
        if self.engine == "no_retry":
            return bool(faults.get("ticket") or faults.get("notification"))
        if self.engine == "no_tenant_check":
            return any(e.get("tenant") != tenant for e in events)
        if self.engine == "title_routes":
            return any(re.search(TITLE_DIRECTIVE_PATTERN, str(e.get("title", "")), re.I) for e in accepted)
        if self.engine == "escalate_high":
            return any(e["severity"] == "high" and (not expected.acknowledgement_before_escalation or e.get("acknowledged") is True)
                       for e in accepted)
        if self.engine == "key_collision":
            seen = {}
            for e in accepted:
                seen.setdefault((e["severity"], e["region"]), set()).add(e["event_id"])
            return any(len(ids) > 1 for ids in seen.values())
        if self.engine == "notify_first":
            return bool(accepted)
        if self.engine == "eu_threshold_up":
            return any(e["region"] == "EU" and e["severity"] == expected.minimum_severity for e in accepted)
        if self.engine == "us_ack_ignored":
            return expected.acknowledgement_before_escalation and any(
                e["severity"] == "critical" and e["region"] == "US" and e.get("acknowledged") is False for e in accepted)
        if self.engine == "title_limit_200":
            return any(200 < len(str(e.get("title", ""))) <= 1000 for e in accepted)
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
    Mutant("wrong_project", "tickets created in the wrong project",
           lambda s: s.model_copy(update={"project": "SRE" if s.project == "OPS" else "OPS"})),
    Mutant("no_retry", "HTTP nodes do not retry transient 503s", engine="no_retry"),
    Mutant("no_tenant_check", "events from another tenant are processed", engine="no_tenant_check"),
    Mutant("title_routes", "obeys a routing directive written in the alert title (channel key or `channel: x`)", engine="title_routes"),
    Mutant("escalate_high", "escalates high-severity events, not only critical ones", engine="escalate_high"),
    Mutant("key_collision", "idempotency key built from severity and region, so different events collide", engine="key_collision"),
    Mutant("notify_first", "notification sent before the ticket exists (ordering defect)", engine="notify_first"),
    Mutant("eu_threshold_up", "EU events need one severity step more than the threshold (region-specific boundary bug)", engine="eu_threshold_up"),
    Mutant("us_ack_ignored", "acknowledgement rule skipped for US events only", engine="us_ack_ignored"),
    Mutant("title_limit_200", "titles over 200 characters rejected although up to 1000 are valid (boundary bug)", engine="title_limit_200"),
]
BY_NAME = {m.name: m for m in MUTANTS}
