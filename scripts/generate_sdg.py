"""Generate a 100-user toy dataset via the operator-supplied NVIDIA SDG route.

By default, 100 users / five users per batch = 20 model requests. No automatic
request retries. Validated batches are checkpointed for explicit resume.
"""
import argparse
import json
import re
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from sim_engine.config import llm_settings
from sim_engine.evidence import digest, dump
from sim_engine.scenarios import generate, load_scenarios, write_scenarios
from sim_engine.world import UserSimulator


class GeneratedUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    session1: str
    session2: str
    # Some models echo these supplied annotations. Accept only unchanged values.
    locale: str | None = None
    expertise: str | None = None


def parse_batch(content: str, scenarios: list) -> dict[str, dict[str, str]]:
    text = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, flags=re.DOTALL)
    payload = json.loads(fenced.group(1).strip() if fenced else text)
    if not isinstance(payload, dict) or set(payload) != {"users"}:
        raise ValueError("SDG must return one JSON object containing only users")
    rows = [GeneratedUser.model_validate(row) for row in payload["users"]]
    expected = {s.scenario_id: s for s in scenarios}
    if len(rows) != len(expected) or {row.scenario_id for row in rows} != set(expected):
        raise ValueError("SDG returned missing, extra, or duplicate user IDs")
    result = {}
    tokens = lambda value: set(re.findall(r"\b(viewer|admin|analytics|email|chat)\b", value.lower()))
    for row in rows:
        source = expected[row.scenario_id]
        if row.locale is not None and row.locale != source.persona.locale:
            raise ValueError("SDG changed the supplied locale")
        if row.expertise is not None and row.expertise != source.persona.expertise:
            raise ValueError("SDG changed the supplied expertise")
        simulator = UserSimulator(source)
        messages = {"1": row.session1.strip(), "2": row.session2.strip()}
        for session in (1, 2):
            if not messages[str(session)] or tokens(messages[str(session)]) != tokens(simulator.initial_message(session)):
                raise ValueError(f"SDG changed task tokens for {row.scenario_id}")
        result[row.scenario_id] = messages
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--max-requests", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--population", type=Path, default=Path("configs/population.json"))
    parser.add_argument("--input", type=Path, help="Optional existing development scenarios instead of generated seeds")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.count < 1 or args.batch_size < 1 or args.max_requests < 1:
        raise ValueError("Count, batch size, and request budget must be positive")
    if args.out.exists():
        raise FileExistsError("Choose a new output file; an existing completed dataset is never overwritten")
    scenarios = load_scenarios(args.input) if args.input else generate(
        args.population, args.count, args.seed, "representative", "development")
    if any(s.split != "development" for s in scenarios):
        raise ValueError("Use development scenarios for SDG; keep the holdout independent")
    if len(scenarios) > 100:
        raise ValueError("Toy SDG is capped at 100 users. Use --input with at most 100 rows")
    settings = llm_settings("sdg")
    run_fingerprint = digest({"scenarios": [s.model_dump() for s in scenarios],
                              "settings": settings.public_metadata()})
    checkpoint = args.out.with_suffix(".partial.jsonl")
    completed = {}
    if checkpoint.exists():
        if not args.resume:
            raise FileExistsError("Partial output exists. Inspect it, then use --resume to continue")
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["run_fingerprint"] != run_fingerprint:
                raise ValueError("Resume settings or scenario inputs differ from the checkpoint")
            completed[row["scenario_id"]] = row["messages"]
    remaining = [s for s in scenarios if s.scenario_id not in completed]
    planned = (len(remaining) + args.batch_size - 1) // args.batch_size
    if planned > args.max_requests:
        raise ValueError(f"Planned {planned} requests exceeds --max-requests={args.max_requests}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"Users: {len(scenarios)}; cached: {len(completed)}; planned requests: {planned}", flush=True)
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0}
    usage_available = True
    requests_made = 0
    with OpenAI(api_key=settings.api_key, base_url=settings.base_url,
                timeout=settings.timeout, max_retries=0) as client:
        for offset in range(0, len(remaining), args.batch_size):
            batch = remaining[offset:offset + args.batch_size]
            seeds = [{"scenario_id": s.scenario_id, "locale": s.persona.locale,
                      "expertise": s.persona.expertise,
                      "session1": UserSimulator(s).initial_message(1),
                      "session2": UserSimulator(s).initial_message(2)} for s in batch]
            request = {
                "model": settings.model,
                "messages": [
                    {"role": "system", "content": (
                        'Paraphrase fictional service-desk requests. Return only JSON: {"users":'
                        '[{"scenario_id":"...","session1":"...","session2":"..."}]}.'
                        " Keep IDs and language, facts, roles, named workspace, ambiguity and notification"
                        " choices exactly. Preserve literal tokens viewer/admin/analytics/email/chat when"
                        " present; do not add absent tokens. Adapt phrasing to expertise. Keep each"
                        " message under 35 words. Never add hidden facts or resolve an ambiguous request.")},
                    {"role": "user", "content": json.dumps({"users": seeds}, ensure_ascii=False)},
                ],
                "temperature": settings.temperature,
                "max_tokens": settings.max_tokens,
            }
            if settings.response_format == "json_object":
                request["response_format"] = {"type": "json_object"}
            if settings.enable_thinking is not None:
                request["extra_body"] = {"chat_template_kwargs": {"enable_thinking": settings.enable_thinking}}
            requests_made += 1
            response = client.chat.completions.create(**request)
            # Keep diagnostic output even when token limits or validation reject a batch.
            with args.out.with_suffix(".requests.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"request_index": requests_made,
                    "scenario_ids": [s.scenario_id for s in batch],
                    "inference": settings.public_metadata(),
                    "response": response.model_dump(exclude_none=True)}, ensure_ascii=False) + "\n")
            if not response.choices or response.choices[0].finish_reason == "length":
                raise RuntimeError("SDG output missing or truncated; reduce batch size or increase SDG max tokens")
            messages = parse_batch(response.choices[0].message.content or "", batch)
            usage = response.usage
            if usage is None or usage.prompt_tokens is None or usage.completion_tokens is None:
                usage_available = False
            else:
                usage_totals["prompt_tokens"] += usage.prompt_tokens
                usage_totals["completion_tokens"] += usage.completion_tokens
            with checkpoint.open("a", encoding="utf-8") as stream:
                for sid, texts in messages.items():
                    stream.write(json.dumps({"run_fingerprint": run_fingerprint, "scenario_id": sid,
                                             "messages": texts}, ensure_ascii=False) + "\n")
            completed.update(messages)
            print(f"Completed {len(completed)}/{len(scenarios)} users", flush=True)
    output = []
    for scenario in scenarios:
        row = scenario.model_copy(deep=True)
        row.scenario_id += "-sdg"
        row.session_messages = completed[scenario.scenario_id]
        row.lineage = {**row.lineage, "linguistic_generator": "nvidia-inference-sdk",
                       "sdg_model": settings.model, "parent_digest": digest(scenario.model_dump()),
                       "semantic_review_required": True}
        output.append(row)
    write_scenarios(args.out, output)
    dump(args.out.with_suffix(".sdg.json"), {
        "users": len(output), "batch_size": args.batch_size, "requests_this_invocation": requests_made,
        "inference": settings.public_metadata(), "usage_this_invocation": usage_totals if usage_available else None,
        "note": "Structural validation only; review meaning. Resume usage covers the current invocation only.",
    })
    print(f"Wrote {args.out}; review semantics before evaluating the generated messages.")


if __name__ == "__main__":
    main()
