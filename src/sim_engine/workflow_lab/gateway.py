"""Authenticated creator gateway. Creates drafts; never activates workflows."""
import hmac
import json
import os
import sqlite3
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import Field

from sim_engine.evidence import Journal, dump

from .compiler import compile_workflow
from .contracts import Model, Spec
from .creator import CreatorMemory, enforce_policy, llm, rules
from .evaluate import release_identity
from .migration import Migration


class DraftRequest(Model):
    tenant: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    user: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    message: str = Field(min_length=1, max_length=10000)


class Gateway:
    def __init__(self, controller_db: Path, output: Path, runtime, backend="rules", import_drafts=False):
        self.controller_db, self.output, self.runtime = controller_db, output, runtime
        self.backend, self.import_drafts = backend, import_drafts
        output.mkdir(parents=True, exist_ok=True)
        self.memory_db = output / "creator-memory.sqlite"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS memories (tenant TEXT, user TEXT, revision INTEGER, value TEXT, PRIMARY KEY(tenant,user));
                CREATE TABLE IF NOT EXISTS conversations (tenant TEXT, user TEXT, session TEXT, value TEXT, PRIMARY KEY(tenant,user,session));
            """)

    def connect(self):
        return sqlite3.connect(self.memory_db, timeout=30)

    def submit(self, request: DraftRequest, _shadow=False) -> dict:
        migration = Migration(self.controller_db)
        try:
            state = migration.status()
            if state["release"] != release_identity(self.backend) or state["executor"] != self.runtime.name:
                raise ValueError("Gateway configuration differs from the evidence-bound release")
            assignment = migration.route(request.tenant, request.session_id)
        finally:
            migration.close()
        if assignment["arm"] == "drain":
            return {"status": "drain", "message": "Candidate session paused for reconciliation; do not change its schema in flight."}
        if _shadow:
            if state["phase"] != "shadow" or state["paused"]:
                raise ValueError("Shadow copies require the shadow stage")
            assignment = {**assignment, "arm": "candidate", "shadow": True}
        variant = assignment["arm"]
        with self.connect() as db:
            saved = db.execute("SELECT revision,value FROM memories WHERE tenant=? AND user=?", (request.tenant, request.user)).fetchone()
            history = db.execute("SELECT value FROM conversations WHERE tenant=? AND user=? AND session=?",
                                 (request.tenant, request.user, request.session_id)).fetchone()
        previous = None
        revision = saved[0] if saved else 0
        if saved:
            snapshot = json.loads(saved[1])
            if snapshot["scope"] != {"tenant": request.tenant, "user": request.user}:
                raise ValueError("Persisted memory scope mismatch")
            previous = Spec.model_validate(snapshot["data"] if snapshot["schema"] == 1 else
                                           {k: v["value"] for k, v in snapshot["data"].items()})
        messages = json.loads(history[0]) if history else []
        messages.append({"role": "user", "content": request.message})
        folder = self.output / "drafts" / uuid.uuid4().hex
        journal = Journal(folder / "events.jsonl", tenant=request.tenant, user=request.user,
                          session=request.session_id, variant=variant)
        journal.emit("gateway.received", assignment=assignment, memory_revision=revision,
                     source="gateway-request", previous_memory_schema=json.loads(saved[1])["schema"] if saved else None)
        reply = llm(messages, previous, journal, variant) if variant == "candidate" and self.backend == "llm" else rules(messages, previous, variant)
        journal.emit("gateway.creator.reply", reply=reply.model_dump())
        if reply.status == "draft":
            if reply.specification is None:
                raise ValueError("Draft requires a specification")
            enforce_policy(reply.specification)
        messages.append({"role": "assistant", "content": reply.question or reply.explanation or reply.status})
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT revision FROM memories WHERE tenant=? AND user=?", (request.tenant, request.user)).fetchone()
            if (current[0] if current else 0) != revision:
                raise ValueError("Concurrent memory change; retry after reading current state")
            if reply.status == "draft":
                memory = CreatorMemory(request.tenant, request.user, reply.specification,
                                       version=2 if variant == "candidate" else 1)
                db.execute("INSERT OR REPLACE INTO memories VALUES (?,?,?,?)", (request.tenant, request.user,
                           revision + 1, json.dumps(memory.snapshot())))
                dump(folder / "memory.json", memory.snapshot())
            db.execute("INSERT OR REPLACE INTO conversations VALUES (?,?,?,?)",
                       (request.tenant, request.user, request.session_id, json.dumps(messages)))
        result = {"status": reply.status, "assignment": assignment, "question": reply.question,
                  "explanation": reply.explanation, "active": False, "scope": "fixture"}
        if reply.status == "draft":
            namespace = self.runtime.create_scope(request.tenant, False, False)
            workflow = compile_workflow(reply.specification, namespace, request.tenant,
                        getattr(self.runtime, "internal_fixture", "http://fixtures:8091"), variant)
            dump(folder / "workflow.json", workflow)
            result.update(specification=reply.specification.model_dump(), artifact=str(folder / "workflow.json"),
                          namespace=namespace)
            if self.import_drafts:
                if self.runtime.name != "n8n":
                    raise ValueError("Draft import requires the n8n executor")
                result["n8n_draft"] = self.runtime.import_draft(workflow)
        dump(folder / "receipt.json", result)
        if state["phase"] == "shadow" and not _shadow:
            # Copy the same incoming request to a separate candidate conversation/memory
            # store. Candidate drafts are never imported or returned as the user result.
            try:
                shadow_gateway = Gateway(self.controller_db, self.output / "shadow", self.runtime,
                                         self.backend, import_drafts=False)
                shadow_result = shadow_gateway.submit(request, _shadow=True)
                journal.emit("gateway.shadow.compared", candidate_status=shadow_result["status"],
                             candidate_artifact=shadow_result.get("artifact"), user_result_arm="baseline")
            except Exception as exc:
                journal.emit("gateway.shadow.error", error_type=type(exc).__name__, user_result_arm="baseline")
        return result


def make_server(gateway: Gateway, host="127.0.0.1", port=8088, token=None):
    token = token if token is not None else os.getenv("N8N_LAB_GATEWAY_TOKEN", "")
    if len(token) < 16:
        raise ValueError("Set N8N_LAB_GATEWAY_TOKEN to a local gateway token of at least 16 characters")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if self.path != "/v1/drafts":
                self.send_error(404); return
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.send_error(401); return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 20000:
                    raise ValueError("Request body too large")
                request = DraftRequest.model_validate_json(self.rfile.read(size))
                data = json.dumps(gateway.submit(request)).encode()
                self.send_response(200)
            except (ValueError, KeyError):
                data = json.dumps({"error": "request_or_policy_conflict"}).encode()
                self.send_response(409)
            except Exception as exc:
                data = json.dumps({"error": type(exc).__name__}).encode()
                self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return ThreadingHTTPServer((host, port), Handler)


def serve(gateway: Gateway, host="127.0.0.1", port=8088):
    server = make_server(gateway, host, port)
    print(f"Draft-only creator gateway: http://{host}:{port}/v1/drafts", flush=True)
    server.serve_forever()
