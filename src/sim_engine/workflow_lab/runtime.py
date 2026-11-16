import json
import os
import re
from pathlib import Path
from urllib.parse import quote

import httpx

from sim_engine.config import load_environment

from .compiler import compile_workflow
from .contracts import Spec
from .fixtures import FixtureStore


class ReferenceRuntime:
    """Python semantic execution. This never claims that n8n ran the workflow."""
    name = "reference"

    def __init__(self, database: Path):
        self.store = FixtureStore(database)

    def create_scope(self, tenant: str, ticket_fault: bool, notification_fault: bool) -> str:
        return self.store.create(tenant, ticket_fault, notification_fault)

    def execute(self, spec: Spec, namespace: str, tenant: str, events: list[dict], variant: str) -> list[dict]:
        responses = []
        for delivery, e in enumerate(events):
            levels = ["low", "medium", "high", "critical"]
            if (e.get("tenant") != tenant or not isinstance(e.get("event_id"), str) or
                    not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", e["event_id"]) or e.get("severity") not in levels or
                    e.get("region") not in ("EU", "US") or not isinstance(e.get("title"), str) or
                    len(e["title"]) > 1000 or not isinstance(e.get("service"), str) or not isinstance(e.get("acknowledged"), bool)):
                responses.append({"status": "rejected"}); continue
            if levels.index(e["severity"]) < levels.index(spec.minimum_severity):
                responses.append({"status": "filtered"}); continue
            event = {k: e[k] for k in ("event_id", "tenant", "severity", "region", "title", "service", "acknowledged")}
            if not spec.minimize_personal_data:
                event = dict(e)
            body = {"namespace": namespace, "tenant": tenant, "event": event, "project": spec.project,
                    "channel": spec.eu_channel if e["region"] == "EU" else spec.default_channel,
                    "effect_key": e["event_id"] + ("" if spec.deduplicate and variant != "baseline" else f":{delivery}"),
                    "escalate": e["severity"] == "critical" and
                                (not spec.acknowledgement_before_escalation or e["acknowledged"])}
            status = 200
            for kind in ("tickets", "notifications", "escalations"):
                if kind == "escalations" and not body["escalate"]:
                    continue
                status, response = self.store.apply(kind, body)
                if status >= 500 and variant == "candidate":
                    status, response = self.store.apply(kind, body)
                if status != 200:
                    break
            responses.append({"status": "completed" if status == 200 else "error", "http_status": status})
        return responses

    def snapshot(self, namespace: str) -> dict:
        return self.store.snapshot(namespace)


class N8nRuntime:
    """Actual self-hosted REST import/activation/webhook/fixture verification adapter."""
    name = "n8n"

    def __init__(self, allow_activation=False):
        load_environment()
        self.base = os.getenv("N8N_LAB_URL", "http://127.0.0.1:5680").rstrip("/")
        self.fixture = os.getenv("N8N_LAB_FIXTURE_URL", "http://127.0.0.1:8091").rstrip("/")
        self.internal_fixture = os.getenv("N8N_LAB_FIXTURE_INTERNAL_URL", "http://fixtures:8091").rstrip("/")
        self.key = os.getenv("N8N_LAB_API_KEY", "")
        if not self.key:
            raise ValueError("Set N8N_LAB_API_KEY for your dedicated self-hosted instance")
        self.allow_activation = allow_activation
        self.publish_action = os.getenv("N8N_LAB_PUBLISH_ACTION", "publish")
        if self.publish_action not in ("publish", "activate"):
            raise ValueError("N8N_LAB_PUBLISH_ACTION must be publish or activate")
        self.created: list[dict] = []

    def api(self, method, path, payload=None):
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.request(method, self.base + "/api/v1" + path,
                headers={"X-N8N-API-KEY": self.key}, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"n8n API {method} failed with status {response.status_code}")
        return response.json() if response.content else {}

    def create_scope(self, tenant: str, ticket_fault: bool, notification_fault: bool) -> str:
        with httpx.Client(timeout=15) as client:
            response = client.post(self.fixture + "/v1/namespaces", json={"tenant": tenant,
                "ticket_fault": ticket_fault, "notification_fault": notification_fault})
            response.raise_for_status()
            return response.json()["namespace"]

    def import_draft(self, workflow: dict) -> dict:
        result = self.api("POST", "/workflows", workflow)
        record = {"id": result["id"], "name": workflow["name"], "versionId": result.get("versionId"), "active": False}
        self.created.append(record)
        return record

    def execute(self, spec: Spec, namespace: str, tenant: str, events: list[dict], variant: str) -> list[dict]:
        if not self.allow_activation:
            raise ValueError("Actual fixture execution requires --allow-activation on the dedicated lab instance")
        workflow = compile_workflow(spec, namespace, tenant, self.internal_fixture, variant)
        record = self.import_draft(workflow)
        workflow_id = quote(str(record["id"]), safe="")
        activation = {"versionId": record["versionId"]} if record["versionId"] else {}
        responses = []
        try:
            record["active"] = "activation-pending"
            self.api("POST", f"/workflows/{workflow_id}/{self.publish_action}", activation)
            record["active"] = True
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                for delivery, event in enumerate(events):
                    response = client.post(self.base + "/webhook/sim-engine-" + namespace,
                        json={"event": event, "delivery_id": str(delivery)})
                    responses.append({"http_status": response.status_code,
                                      "status": "completed" if response.status_code < 400 else "error"})
        finally:
            unpublish = "unpublish" if self.publish_action == "publish" else "deactivate"
            self.api("POST", f"/workflows/{workflow_id}/{unpublish}")
            record["active"] = False
        return responses

    def snapshot(self, namespace: str) -> dict:
        with httpx.Client(timeout=15) as client:
            response = client.get(self.fixture + "/v1/snapshots/" + quote(namespace, safe=""))
            response.raise_for_status()
            return response.json()
