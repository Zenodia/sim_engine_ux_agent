from copy import deepcopy
from typing import Any

from .evidence import Journal, digest


class Memory:
    """Explicitly scoped synthetic facts, with reversible v1 -> v2 transformation."""

    def __init__(self, version: int, tenant: str, user: str, namespace: str, journal: Journal):
        if version not in (1, 2):
            raise ValueError("Unsupported memory schema")
        self.version = version
        self.scope = {"tenant": tenant, "user": user, "namespace": namespace}
        self.data: dict[str, Any] = {}
        self.journal = journal

    def read(self, key: str) -> Any:
        item = self.data.get(key)
        value = item.get("value") if self.version == 2 and item else item
        self.journal.emit("memory.read", scope=self.scope, key=key, hit=item is not None)
        return deepcopy(value)

    def write(self, key: str, value: Any, source: str = "user_statement") -> None:
        before = digest(self.data)
        self.data[key] = deepcopy(value) if self.version == 1 else {
            "value": deepcopy(value), "source": source, "revision": self.revision(key) + 1,
        }
        self.journal.emit("memory.write", scope=self.scope, key=key, value=value,
                          source=source, before=before, after=digest(self.data))

    def revision(self, key: str) -> int:
        item = self.data.get(key)
        return item.get("revision", 0) if isinstance(item, dict) else 0

    def snapshot(self) -> dict:
        return {"schema_version": self.version, "scope": self.scope, "data": deepcopy(self.data)}

    def migrate(self, version: int) -> "Memory":
        if version not in (1, 2):
            raise ValueError("Unsupported target schema")
        other = Memory(version, self.scope["tenant"], self.scope["user"],
                       self.scope["namespace"], self.journal)
        for key in self.data:
            other.write(key, self.read(key), source=f"migration_from_v{self.version}")
        self.journal.emit("memory.migrate", source_version=self.version,
                          target_version=version, scope=self.scope,
                          source_digest=digest(self.snapshot()), target_digest=digest(other.snapshot()))
        return other

