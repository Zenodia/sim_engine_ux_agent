from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Persona(Contract):
    user_id: str
    tenant_id: str
    role: Literal["analyst", "contractor"]
    locale: Literal["en", "de"]
    expertise: Literal["novice", "expert"]
    patience: int = Field(ge=2, le=8)
    initial_channel: Literal["email", "chat"]


class Scenario(Contract):
    schema_version: Literal[1] = 1
    scenario_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,220}$")
    seed: int
    split: Literal["development", "holdout"]
    suite: Literal["representative", "stress"]
    cohort: str
    persona: Persona
    # Private simulator/verifier configuration. Never pass this object to an agent.
    requested_role: Literal["viewer", "admin"]
    changed_preference: bool
    ambiguous_workspace: bool
    timeout_after_commit: bool
    revoked_access: bool
    tool_injection: bool
    stale_memory: bool
    workspace: str = "analytics"
    session_messages: dict[str, str] = Field(default_factory=dict)
    lineage: dict[str, Any] = Field(default_factory=dict)


class Action(Contract):
    tool: Literal[
        "read_memory", "write_memory", "get_policy", "get_access", "grant_access",
        "notify", "ask_user", "finish"
    ]
    args: dict[str, Any] = Field(default_factory=dict)


class Check(Contract):
    name: str
    passed: bool
    detail: str = ""


class Outcome(Contract):
    run_id: str
    scenario_id: str
    variant: str
    backend: str
    cohort: str
    split: str
    suite: str
    status: Literal["completed", "error"]
    checks: list[Check]
    success: bool
    safety_failure: bool
    user_rating_proxy: int
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    error: str | None = None
    migration_mode: str = "cold"

