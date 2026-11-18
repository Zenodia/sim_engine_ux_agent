"""Compile a bounded incident specification into native n8n workflow JSON."""
import json
import uuid
from urllib.parse import urlsplit

from sim_engine.evidence import digest

from .contracts import Spec


PLAN_JS = r'''
const cfg = __CONFIG__;
const input = $input.first().json;
const body = input.body || input;
const event = body.event || {};
const severity = {low: 0, medium: 1, high: 2, critical: 3};
const valid = event.tenant === cfg.tenant && typeof event.event_id === 'string' &&
  /^[A-Za-z0-9_-]{1,100}$/.test(event.event_id) &&
  Object.hasOwn(severity, event.severity) && ['EU', 'US'].includes(event.region) &&
  typeof event.title === 'string' && event.title.length <= 1000 &&
  typeof event.service === 'string' && typeof event.acknowledged === 'boolean';
if (!valid) return [{json: {allowed: false, status: 'rejected', namespace: cfg.namespace}}];
if (severity[event.severity] < severity[cfg.spec.minimum_severity])
  return [{json: {allowed: false, status: 'filtered', namespace: cfg.namespace}}];
const clean = cfg.spec.minimize_personal_data ? {
  event_id: event.event_id, tenant: cfg.tenant, severity: event.severity,
  region: event.region, title: event.title, service: event.service,
  acknowledged: event.acknowledged
} : {...event};
const suffix = cfg.spec.deduplicate && !cfg.legacy ? '' : ':' + String(body.delivery_id || 'delivery');
return [{json: {allowed: true, status: 'planned', namespace: cfg.namespace,
  tenant: cfg.tenant, event: clean, project: cfg.spec.project,
  channel: event.region === 'EU' ? cfg.spec.eu_channel : cfg.spec.default_channel,
  effect_key: event.event_id + suffix,
  escalate: event.severity === 'critical' &&
    (!cfg.spec.acknowledgement_before_escalation || event.acknowledged)}}];
'''


# Deliberate engine-level defects used only by verifier certification (mutation testing).
ENGINE_MUTATIONS = ("no_retry", "no_tenant_check", "title_routes", "escalate_high", "key_collision", "notify_first",
                    "eu_threshold_up", "us_ack_ignored", "title_limit_200")
# "title_routes" models a naive workflow that obeys a routing directive found inside alert text: a JSON "channel"
# key or a `channel: name` phrase in the title overrides the destination (prompt-injection style compliance).
TITLE_DIRECTIVE_PATTERN = r'(?:"channel"\s*:\s*"|\bchannel\s*[:=]\s*#?)([A-Za-z0-9_-]+)'
_ROUTE_JS = "channel: event.region === 'EU' ? cfg.spec.eu_channel : cfg.spec.default_channel,"
_ESCALATE_JS = "escalate: event.severity === 'critical' &&"
_KEY_JS = "effect_key: event.event_id + suffix,"
_THRESHOLD_JS = "severity[event.severity] < severity[cfg.spec.minimum_severity])"
_ACK_JS = "(!cfg.spec.acknowledgement_before_escalation || event.acknowledged)}}];"
_TITLE_JS = "event.title.length <= 1000"


def _patch(code: str, old: str, new: str) -> str:
    patched = code.replace(old, new, 1)
    assert patched != code, "mutation anchor not found in the plan code; update the mutation"
    return patched


def plan_code(spec: Spec, namespace: str, tenant: str, legacy: bool = False, mutation: str | None = None) -> str:
    code = PLAN_JS.replace("__CONFIG__", json.dumps({"spec": spec.model_dump(), "namespace": namespace,
                                                    "tenant": tenant, "legacy": legacy}))
    if mutation == "no_tenant_check":
        code = _patch(code, "event.tenant === cfg.tenant && ", "")
    elif mutation == "title_routes":
        code = _patch(code, _ROUTE_JS, "channel: ((m) => m ? m[1] : (" + _ROUTE_JS[len("channel: "):-1] +
                      "))(new RegExp(" + json.dumps(TITLE_DIRECTIVE_PATTERN) + ", 'i').exec(event.title)),")
    elif mutation == "escalate_high":
        code = _patch(code, _ESCALATE_JS, "escalate: (event.severity === 'critical' || event.severity === 'high') &&")
    elif mutation == "key_collision":
        code = _patch(code, _KEY_JS, "effect_key: event.severity + ':' + event.region + suffix,")
    elif mutation == "eu_threshold_up":
        code = _patch(code, _THRESHOLD_JS, "severity[event.severity] < severity[cfg.spec.minimum_severity] + (event.region === 'EU' ? 1 : 0))")
    elif mutation == "us_ack_ignored":
        code = _patch(code, _ACK_JS, "(!cfg.spec.acknowledgement_before_escalation || event.acknowledged || event.region === 'US')}}];")
    elif mutation == "title_limit_200":
        code = _patch(code, _TITLE_JS, "event.title.length <= 200")
    return code


def _if(field: str) -> dict:
    return {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
        "conditions": [{"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, field)), "leftValue": "={{ $json." + field + " }}",
                        "rightValue": True, "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
        "combinator": "and"}, "options": {}}


def compile_workflow(spec: Spec, namespace: str, tenant: str, fixture_url: str,
                     variant: str = "candidate", mutation: str | None = None) -> dict:
    url = urlsplit(fixture_url)
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Fixture URL must be an HTTP origin/path without credentials or query parameters")
    if variant not in ("baseline", "candidate"):
        raise ValueError("Unknown compiler variant")
    if mutation is not None and mutation not in ENGINE_MUTATIONS:
        raise ValueError("Unknown engine mutation")
    retry = variant == "candidate" and mutation != "no_retry"
    path = "sim-engine-" + namespace
    nodes = []
    def node(name, kind, version, parameters, x, y=0, **settings):
        value = {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, namespace + name)), "name": name,
                 "type": "n8n-nodes-base." + kind, "typeVersion": version,
                 "position": [x, y], "parameters": parameters, **settings}
        if kind == "webhook":
            value["webhookId"] = str(uuid.uuid5(uuid.NAMESPACE_DNS, namespace))
        nodes.append(value)
    node("Incident webhook", "webhook", 2.1,
         {"httpMethod": "POST", "path": path, "responseMode": "lastNode", "responseData": "firstEntryJson", "options": {}}, 0)
    node("Validate and plan", "code", 2, {"mode": "runOnceForAllItems", "language": "javaScript",
          "jsCode": plan_code(spec, namespace, tenant, variant == "baseline", mutation)}, 240)
    node("Eligible incident", "if", 2.2, _if("allowed"), 480)
    for i, (name, route) in enumerate((("Create ticket", "tickets"), ("Notify team", "notifications"))):
        node(name, "httpRequest", 4.3, {"method": "POST", "url": fixture_url.rstrip("/") + "/v1/" + route,
             "sendBody": True, "contentType": "json", "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json) }}",
             "options": {"timeout": 10000, "redirect": {"redirect": {"followRedirects": False}}}},
             720 + i * 240, retryOnFail=retry, maxTries=2, waitBetweenTries=100)
    node("Escalation required", "if", 2.2, _if("escalate"), 1200)
    node("Escalate incident", "httpRequest", 4.3, {"method": "POST", "url": fixture_url.rstrip("/") + "/v1/escalations",
         "sendBody": True, "contentType": "json", "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json) }}",
         "options": {"timeout": 10000, "redirect": {"redirect": {"followRedirects": False}}}},
         1440, retryOnFail=retry, maxTries=2, waitBetweenTries=100)
    node("Execution receipt", "code", 2, {"mode": "runOnceForAllItems", "language": "javaScript",
         "jsCode": "return $input.all().map(item => ({json: {status: item.json.allowed ? 'completed' : item.json.status, namespace: item.json.namespace}}));"}, 1680)
    def link(target):
        return {"node": target, "type": "main", "index": 0}
    connections = {
        "Incident webhook": {"main": [[link("Validate and plan")]]},
        "Validate and plan": {"main": [[link("Eligible incident")]]},
        "Eligible incident": {"main": [[link("Notify team" if mutation == "notify_first" else "Create ticket")], [link("Execution receipt")]]},
        "Create ticket": {"main": [[link("Escalation required" if mutation == "notify_first" else "Notify team")]]},
        "Notify team": {"main": [[link("Create ticket" if mutation == "notify_first" else "Escalation required")]]},
        "Escalation required": {"main": [[link("Escalate incident")], [link("Execution receipt")]]},
        "Escalate incident": {"main": [[link("Execution receipt")]]},
    }
    return {"name": "sim-engine:" + namespace, "nodes": nodes, "connections": connections,
            "settings": {"executionOrder": "v1", "saveDataSuccessExecution": "all", "saveDataErrorExecution": "all"}}


def artifact_digest(workflow: dict) -> str:
    """Content identity includes destinations and compiled tenant/namespace, not a name only."""
    return digest(workflow)
