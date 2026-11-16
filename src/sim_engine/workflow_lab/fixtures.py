"""Durable fixture API. It never calls a real ticketing or messaging service."""
import json
import sqlite3
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FixtureStore:
    def __init__(self, database: Path):
        database.parent.mkdir(parents=True, exist_ok=True)
        self.path = database
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS namespaces (id TEXT PRIMARY KEY, tenant TEXT, faults TEXT);
                CREATE TABLE IF NOT EXISTS effects (
                    namespace TEXT, kind TEXT, effect_key TEXT, payload TEXT,
                    PRIMARY KEY(namespace, kind, effect_key));
                CREATE TABLE IF NOT EXISTS attempts (namespace TEXT, kind TEXT, status TEXT);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def create(self, tenant: str, ticket_fault=False, notification_fault=False) -> str:
        namespace = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO namespaces VALUES (?,?,?)", (namespace, tenant,
                       json.dumps({"tickets": bool(ticket_fault), "notifications": bool(notification_fault)})))
        return namespace

    def apply(self, kind: str, body: dict) -> tuple[int, dict]:
        if kind not in ("tickets", "notifications", "escalations"):
            return 404, {"error": "unknown_effect"}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            scope = db.execute("SELECT * FROM namespaces WHERE id=?", (body.get("namespace"),)).fetchone()
            if scope is None or scope["tenant"] != body.get("tenant"):
                return 403, {"error": "invalid_scope"}
            key = body.get("effect_key")
            if not isinstance(key, str) or not key:
                return 400, {"error": "missing_effect_key"}
            faults = json.loads(scope["faults"])
            trigger = faults.get(kind, False)
            if trigger:
                faults[kind] = False
                db.execute("UPDATE namespaces SET faults=? WHERE id=?", (json.dumps(faults), scope["id"]))
            if trigger and kind == "notifications":
                db.execute("INSERT INTO attempts VALUES (?,?,?)", (scope["id"], kind, "503-before-write"))
                return 503, {"error": "temporary_notification_failure"}
            existing = db.execute("SELECT payload FROM effects WHERE namespace=? AND kind=? AND effect_key=?",
                                  (scope["id"], kind, key)).fetchone()
            if existing is not None and json.loads(existing["payload"]) != body:
                db.execute("INSERT INTO attempts VALUES (?,?,?)", (scope["id"], kind, "409-idempotency-conflict"))
                return 409, {"error": "idempotency_key_reused_with_changed_payload"}
            db.execute("INSERT OR IGNORE INTO effects VALUES (?,?,?,?)",
                       (scope["id"], kind, key, json.dumps(body, sort_keys=True)))
            db.execute("INSERT INTO attempts VALUES (?,?,?)", (scope["id"], kind,
                       "503-after-commit" if trigger else "200"))
        if trigger:
            return 503, {"error": "timeout_after_commit", "outcome": "unknown"}
        return 200, {**body, "status": "effect-recorded"}

    def snapshot(self, namespace: str) -> dict:
        with self.connect() as db:
            scope = db.execute("SELECT tenant FROM namespaces WHERE id=?", (namespace,)).fetchone()
            if scope is None:
                raise ValueError("Unknown namespace")
            return {"tenant": scope["tenant"], "namespace": namespace,
                    "effects": [{"kind": row["kind"], "key": row["effect_key"], "payload": json.loads(row["payload"])}
                        for row in db.execute("SELECT * FROM effects WHERE namespace=? ORDER BY rowid", (namespace,))],
                    "attempts": [dict(row) for row in db.execute(
                        "SELECT kind,status FROM attempts WHERE namespace=?", (namespace,))]}


def serve(database: Path, host="127.0.0.1", port=8091):
    store = FixtureStore(database)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, value):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/healthz":
                return self.reply(200, {"status": "ok", "service": "fictional-enterprise-fixtures"})
            if self.path.startswith("/v1/snapshots/"):
                try:
                    return self.reply(200, store.snapshot(self.path.rsplit("/", 1)[1]))
                except ValueError:
                    return self.reply(404, {"error": "unknown_namespace"})
            self.reply(404, {"error": "not_found"})

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 100_000:
                    return self.reply(413, {"error": "invalid_body_size"})
                body = json.loads(self.rfile.read(length))
                if self.path == "/v1/namespaces":
                    namespace = store.create(body["tenant"], body.get("ticket_fault", False), body.get("notification_fault", False))
                    return self.reply(201, {"namespace": namespace})
                status, response = store.apply(self.path.removeprefix("/v1/"), body)
                self.reply(status, response)
            except (ValueError, KeyError, TypeError):
                self.reply(400, {"error": "invalid_request"})
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Fixture API on {host}:{port}; database={database}", flush=True)
    server.serve_forever()
