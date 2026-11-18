"""Optional batched Nemotron paraphrases of the workflow-authoring conversations."""
import json
import re
from pathlib import Path

from openai import OpenAI
from pydantic import Field

from sim_engine.config import llm_settings
from sim_engine.evidence import digest, dump

from .contracts import Model
from .creator import author, rules
from .tasks import write


class Texts(Model):
    task_id: str
    initial_request: str = Field(min_length=1)
    revision_request: str = Field(min_length=1)


def paraphrase(tasks, output: Path, batch_size=5, max_requests=20, max_tokens=2048, resume=False):
    if not 1 <= len(tasks) <= 100 or batch_size < 1 or max_requests < 1 or max_tokens < 1:
        raise ValueError("Use 1-100 users and positive batch/request/token limits")
    if output.exists():
        raise FileExistsError("Choose a new output file")
    settings = llm_settings("sdg")
    identity = digest({"tasks": [t.model_dump() for t in tasks], "model": settings.public_metadata(),
                       "max_tokens": max_tokens, "generator": "workflow-conversation-sdg-v1"})
    checkpoint = output.with_suffix(".partial.jsonl")
    complete = {}
    if checkpoint.exists():
        if not resume:
            raise ValueError("Checkpoint exists; inspect it and use --resume")
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if item["identity"] != identity:
                raise ValueError("Checkpoint inputs/configuration differ")
            complete[item["task_id"]] = Texts.model_validate(item["texts"])
    pending = [t for t in tasks if t.task_id not in complete]
    if (len(pending) + batch_size - 1) // batch_size > max_requests:
        raise ValueError("Planned SDG requests exceed the per-invocation budget")
    output.parent.mkdir(parents=True, exist_ok=True)
    requests = 0
    with OpenAI(api_key=settings.api_key, base_url=settings.base_url, timeout=settings.timeout, max_retries=0) as client:
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset:offset + batch_size]
            seeds = [{"task_id": t.task_id, "initial_request": t.initial_request, "revision_request": t.revision_request} for t in batch]
            request = {"model": settings.model, "max_tokens": max_tokens, "temperature": settings.temperature,
                "messages": [{"role": "system", "content": (
                    'Paraphrase these enterprise workflow-creation conversations. Return only JSON '
                    '{"tasks":[{"task_id":"...","initial_request":"...","revision_request":"..."}]}. '
                    "Preserve task IDs, every labeled field (Project:, Minimum severity:, Default channel:, EU channel:), "
                    "all field values, and the exact clauses 'without waiting for acknowledgement', "
                    "'now require acknowledgement', and 'ask me for its name' whenever supplied. "
                    "Keep the same session boundaries and constraints. Add no facts or destinations. "
                    "Only vary the surrounding natural-language wording; keep messages concise.")},
                    {"role": "user", "content": json.dumps({"tasks": seeds})}]}
            if settings.enable_thinking is not None:
                request["extra_body"] = {"chat_template_kwargs": {"enable_thinking": settings.enable_thinking}}
            requests += 1
            response = client.chat.completions.create(**request)
            with output.with_suffix(".requests.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(response.model_dump(exclude_none=True)) + "\n")
            if not response.choices or response.choices[0].finish_reason == "length":
                raise RuntimeError("SDG output truncated; reduce batch size or increase --max-tokens")
            text = (response.choices[0].message.content or "").strip()
            fence = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, flags=re.S)
            payload = json.loads(fence.group(1) if fence else text)
            if not isinstance(payload, dict) or set(payload) != {"tasks"}:
                raise ValueError("SDG must return only a tasks collection")
            rows = [Texts.model_validate(r) for r in payload["tasks"]]
            if len(rows) != len(batch) or {r.task_id for r in rows} != {t.task_id for t in batch}:
                raise ValueError("SDG task identity mismatch")
            for row in rows:
                source = next(t for t in batch if t.task_id == row.task_id)
                initial = rules([{"role": "user", "content": row.initial_request}], None, "candidate")
                if initial.status != "draft" or initial.specification != source.expected_initial:
                    raise ValueError("SDG changed initial requirements")
                # Cross-check the bounded contract with the deterministic interpreter.
                class Quiet:
                    def emit(self, *_, **__): pass
                final = author([{"role": "user", "content": row.revision_request}], initial.specification,
                               "rules", "candidate", Quiet(), source.clarification_answers)
                if final != source.expected_final:
                    raise ValueError("SDG changed revised requirements")
            with checkpoint.open("a", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps({"identity": identity, "task_id": row.task_id, "texts": row.model_dump()}) + "\n")
                    complete[row.task_id] = row
            print(f"Workflow SDG: {len(complete)}/{len(tasks)} users", flush=True)
    result = []
    for task in tasks:
        row = task.model_copy(update={"task_id": task.task_id + "-sdg",
            "initial_request": complete[task.task_id].initial_request,
            "revision_request": complete[task.task_id].revision_request})
        result.append(row)
    write(output, result)
    dump(output.with_suffix(".sdg.json"), {"users": len(result), "requests_this_invocation": requests,
        "model": settings.public_metadata(), "max_tokens_used": max_tokens, "source_digest": identity,
        "review": "Reference-parser checks passed; independent human semantic review still required."})
