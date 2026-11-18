import inspect
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sim_engine.evidence import Journal, digest, dump

from . import compiler, creator
from .compiler import artifact_digest, compile_workflow
from .contracts import Check, CreatorTask, Evidence, Result, Spec
from .creator import CreatorMemory, author
from .fixtures import FixtureStore
from .tasks import event_suite_v2, event_suite_v3


def release_identity(backend: str) -> str:
    from . import runtime
    configuration = {"backend": backend, "spec_schema": Spec.model_json_schema(),
                     "compiler": inspect.getsource(compiler), "creator": inspect.getsource(creator),
                     "runtime": inspect.getsource(runtime), "verifier": inspect.getsource(verify_effects),
                     "events": inspect.getsource(event_suite_v2) + inspect.getsource(event_suite_v3), "fixtures": inspect.getsource(FixtureStore)}
    if backend == "llm":
        from sim_engine.config import llm_settings
        configuration["model_configuration"] = llm_settings().public_metadata()
    return "incident-creator-v1:" + digest(configuration)


def verify_effects(expected: Spec, tenant: str, events: list[dict], snapshot: dict) -> list[Check]:
    """Independent oracle over business effects, not a reference workflow graph."""
    rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    accepted = {e["event_id"]: e for e in events if e.get("tenant") == tenant and e.get("event_id") and
                e.get("severity") in rank and rank[e["severity"]] >= rank[expected.minimum_severity] and
                e.get("region") in ("EU", "US")}
    effects = snapshot["effects"]
    checks = []
    for kind in ("tickets", "notifications", "escalations"):
        wanted = set(accepted) if kind != "escalations" else {key for key, e in accepted.items()
            if e["severity"] == "critical" and (not expected.acknowledgement_before_escalation or e["acknowledged"])}
        observed = [effect for effect in effects if effect["kind"] == kind]
        identities = [effect["payload"]["event"]["event_id"] for effect in observed]
        checks.append(Check(name=kind + "_exactly_once", passed=len(identities) == len(wanted) and set(identities) == wanted))
    # Ordering: for every event the ticket must exist before its notification, and the notification before any escalation.
    # (Found by mutation testing: the set-based checks above could not see a workflow that notified first.)
    position = {}
    for index, effect in enumerate(effects):
        position.setdefault((effect["kind"], effect["payload"]["event"]["event_id"]), index)
    sequence = ("tickets", "notifications", "escalations")
    ordered = all(position[(earlier, identity)] < position[(later, identity)]
                  for identity in accepted for i, earlier in enumerate(sequence) for later in sequence[i + 1:]
                  if (earlier, identity) in position and (later, identity) in position)
    checks.append(Check(name="effect_order", passed=ordered))
    notifications = [e["payload"] for e in effects if e["kind"] == "notifications"]
    checks.extend([
        Check(name="regional_routing", passed=all(p["channel"] ==
              (expected.eu_channel if p["event"]["region"] == "EU" else expected.default_channel) for p in notifications)),
        Check(name="ticket_project", passed=all(e["payload"]["project"] == expected.project for e in effects)),
        Check(name="privacy", passed=all(set(e["payload"]["event"]) <=
              {"event_id", "tenant", "severity", "region", "title", "service", "acknowledged"} for e in effects)),
        Check(name="tenant_isolation", passed=all(e["payload"]["tenant"] == tenant and
              e["payload"]["event"]["tenant"] == tenant for e in effects)),
        Check(name="untrusted_title_is_data", passed=all(e["payload"]["channel"] in
              (expected.default_channel, expected.eu_channel) for e in effects)),
    ])
    return checks


def evaluate(tasks: list[CreatorTask], output: Path, runtime, backend="rules", stage="offline", controller=None) -> Evidence:
    output.mkdir(parents=True, exist_ok=False)
    window = str(uuid.uuid4())
    release = release_identity(backend)
    records = []
    if stage == "canary" and controller is None:
        raise ValueError("Canary evidence requires assignments from the migration controller")
    if controller is not None:
        state = controller.status()
        if state["release"] != release or state["executor"] != runtime.name:
            raise ValueError("Selected creator/runtime differs from the experiment release")
        if stage == "canary" and state["phase"] not in ("canary", "expansion", "full"):
            raise ValueError("Start canary only after preceding stages pass")
        if stage == "shadow" and state["phase"] != "shadow":
            raise ValueError("Shadow execution requires passing offline evidence")
    dump(output / "manifest.json", {"window": window, "release": release, "executor": runtime.name,
         "creator_backend": backend, "stage": stage, "scope": "fixture", "user_count": len(tasks),
         "origin": "synthetic", "dataset_digest": digest([t.model_dump() for t in tasks])})
    for task in tasks:
        variants = ["baseline", "candidate"]
        if stage == "canary":
            assignment = controller.route(task.tenant, window + ":" + task.task_id)
            if assignment["arm"] == "drain":
                continue
            variants = [assignment["arm"]]
        for variant in variants:
            folder = output / "episodes" / task.task_id / variant
            journal = Journal(folder / "events.jsonl", task_id=task.task_id, tenant=task.tenant,
                              user=task.user, cohort=task.cohort, variant=variant, window=window)
            started = time.perf_counter()
            namespace = None
            checks, error, workflow_hash = [], None, ""
            try:
                # Both arms start with identical legacy facts from the first session.
                initial = author([{"role": "user", "content": task.initial_request}], None, "rules", "baseline", journal)
                memory = CreatorMemory(task.tenant, task.user, initial)
                before = memory.snapshot()
                dump(folder / "memory-v1.json", before)
                if variant == "candidate":
                    memory = memory.migrate(task.tenant, task.user)
                dump(folder / "memory-start.json", memory.snapshot())
                journal.emit("creator.memory.migration", source=digest(before), target=digest(memory.snapshot()),
                             source_schema=1, target_schema=memory.version)
                messages = [{"role": "user", "content": task.revision_request}]
                spec = author(messages, memory.spec(), backend if variant == "candidate" else "rules",
                              variant, journal, task.clarification_answers)
                memory = CreatorMemory(task.tenant, task.user, spec, version=memory.version)
                dump(folder / "memory-final.json", memory.snapshot())
                journal.emit("creator.memory.updated", snapshot=memory.snapshot())
                dump(folder / "requirements.json", spec.model_dump())
                namespace = runtime.create_scope(task.tenant, task.fault_after_commit, task.notification_failure)
                fixture_url = getattr(runtime, "internal_fixture", "http://fixtures:8091")
                workflow = compile_workflow(spec, namespace, task.tenant, fixture_url, variant)
                workflow_hash = artifact_digest(workflow)
                dump(folder / "workflow.json", workflow)
                dump(folder / "previous-workflow.json", compile_workflow(initial, namespace + "-previous", task.tenant, fixture_url, "baseline"))
                events = event_suite_v3(task.tenant)
                responses = runtime.execute(spec, namespace, task.tenant, events, variant)
                snapshot = runtime.snapshot(namespace)
                dump(folder / "events-input.json", events)
                dump(folder / "execution-responses.json", responses)
                dump(folder / "final-state.json", snapshot)
                journal.emit("workflow.executed", artifact_digest=workflow_hash, executor=runtime.name,
                             deliveries=len(events), namespace=namespace, effects=len(snapshot["effects"]))
                checks = verify_effects(task.expected_final, task.tenant, events, snapshot)
                checks.append(Check(name="memory_scope_preserved", passed=memory.scope == before["scope"]))
            except Exception as exc:
                error = type(exc).__name__
                journal.emit("workflow.error", error_type=error)
                checks.append(Check(name="execution_completed", passed=False, detail=error))
            usage = [json.loads(line)["data"].get("usage") for line in journal.path.read_text(encoding="utf-8").splitlines()
                     if json.loads(line)["kind"] == "creator.model.response"] if journal.path.exists() else []
            input_tokens = output_tokens = None if backend == "llm" and variant == "candidate" else 0
            if usage and all(u and isinstance(u.get("prompt_tokens"), int) and isinstance(u.get("completion_tokens"), int) for u in usage):
                input_tokens = sum(u["prompt_tokens"] for u in usage)
                output_tokens = sum(u["completion_tokens"] for u in usage)
            cost = 0.0 if variant == "baseline" or backend == "rules" else None
            price_in, price_out = os.getenv("SIM_INPUT_USD_PER_MILLION"), os.getenv("SIM_OUTPUT_USD_PER_MILLION")
            if cost is None and price_in and price_out and input_tokens is not None:
                cost = (input_tokens * float(price_in) + output_tokens * float(price_out)) / 1_000_000
            result = Result(task_id=task.task_id, tenant=task.tenant, cohort=task.cohort, variant=variant,
                creator=backend if variant == "candidate" else "rules", executor=runtime.name,
                artifact_digest=workflow_hash, success=error is None and all(c.passed for c in checks),
                checks=checks, latency_ms=(time.perf_counter() - started) * 1000, error=error,
                input_tokens=input_tokens, output_tokens=output_tokens, estimated_cost_usd=cost)
            dump(folder / "outcome.json", result.model_dump())
            journal.emit("workflow.evaluated", result=result.model_dump())
            records.append(result)
        print(f"{stage}: {task.task_id}", flush=True)
    if runtime.name == "n8n":
        dump(output / "n8n-created-workflows.json", runtime.created)
    with (output / "outcomes.jsonl").open("w", encoding="utf-8") as stream:
        stream.write("".join(r.model_dump_json() + "\n" for r in records))
    baseline = [r for r in records if r.variant == "baseline"]
    candidate = [r for r in records if r.variant == "candidate"]
    report = Evidence(evidence_id=str(uuid.uuid4()), release=release, stage=stage, executor=runtime.name,
        observed_at=datetime.now(timezone.utc).isoformat(), window=window, observations=len(records),
        candidate_observations=len(candidate), baseline_observations=len(baseline),
        candidate_failures=sum(not r.success for r in candidate), baseline_failures=sum(not r.success for r in baseline),
        coverage=sorted({r.cohort for r in candidate}), passed=bool(candidate) and all(r.success for r in candidate),
        artifacts_digest=digest([r.model_dump() for r in records]), dataset_digest=digest([t.model_dump() for t in tasks]),
        candidate_mean_latency_ms=sum(r.latency_ms for r in candidate) / len(candidate) if candidate else 0,
        candidate_mean_cost_usd=sum(r.estimated_cost_usd for r in candidate) / len(candidate)
            if candidate and all(r.estimated_cost_usd is not None for r in candidate) else None)
    dump(output / "evidence.json", report.model_dump())
    if stage == "offline":
        instrumentation = report.model_copy(update={"stage": "baseline", "evidence_id": str(uuid.uuid4()),
            "passed": bool(baseline) and all(r.artifact_digest for r in baseline)})
        dump(output / "baseline-evidence.json", instrumentation.model_dump())
    write_report(output, report, records)
    return report


def write_report(output: Path, evidence: Evidence, rows: list[Result]):
    import html
    summary = {v: {"flows": len(part), "successes": sum(r.success for r in part),
                  "errors": sum(bool(r.error) for r in part)}
               for v in ("baseline", "candidate") if (part := [r for r in rows if r.variant == v])}
    dump(output / "summary.json", summary)
    lines = "".join("<tr><td>" + "</td><td>".join(html.escape(str(v)) for v in
        (r.task_id, r.variant, r.cohort, "PASS" if r.success else "FAIL",
         ", ".join(c.name for c in r.checks if not c.passed))) + "</td></tr>" for r in rows)
    (output / "report.html").write_text("<!doctype html><meta charset='utf-8'><title>n8n creator evaluation</title>"
        "<style>body{font:16px system-ui;margin:3em}td,th{padding:.6em;border-bottom:1px solid #ccc}pre{white-space:pre-wrap}</style>"
        "<h1>Incident workflow creator</h1><p>Fixture evidence; executor: " + html.escape(evidence.executor) +
        ". Reference execution is not n8n runtime validation. Production promotion is not authorized.</p><pre>" +
        html.escape(json.dumps(summary, indent=2)) + "</pre><table><tr><th>Task</th><th>Variant</th><th>Cohort</th>"
        "<th>Result</th><th>Failed checks</th></tr>" + lines + "</table>", encoding="utf-8")
