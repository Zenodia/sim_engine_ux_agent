from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Spec(Model):
    """Bounded authoring language. No model-generated code, URLs, or credentials."""
    project: str = Field(default="OPS", pattern=r"^[A-Z][A-Z0-9_-]{0,31}$")
    minimum_severity: Literal["low", "medium", "high", "critical"] = "high"
    default_channel: str = Field(default="ops-general", pattern=r"^[a-z0-9_-]{1,64}$")
    eu_channel: str = Field(default="ops-eu", pattern=r"^[a-z0-9_-]{1,64}$")
    deduplicate: bool = True
    minimize_personal_data: bool = True
    acknowledgement_before_escalation: bool = True


class CreatorTask(Model):
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    tenant: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    user: str
    cohort: str
    initial_request: str
    revision_request: str
    clarification_answers: dict[str, str] = Field(default_factory=dict)
    # Private oracle values. The creator receives messages, never this task object.
    expected_initial: Spec
    expected_final: Spec
    fault_after_commit: bool = False
    notification_failure: bool = False


class AuthorReply(Model):
    status: Literal["draft", "clarify", "decline"]
    specification: Spec | None = None
    question: str | None = None
    clarification_key: Literal["eu_channel", "project", "minimum_severity"] | None = None
    explanation: str = ""


class Check(Model):
    name: str
    passed: bool
    detail: str = ""


class Result(Model):
    task_id: str
    tenant: str
    cohort: str
    variant: Literal["baseline", "candidate"]
    creator: str
    executor: Literal["reference", "n8n"]
    artifact_digest: str
    success: bool
    checks: list[Check]
    latency_ms: float
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None


class Evidence(Model):
    schema_version: Literal[1] = 1
    evidence_id: str
    release: str
    protocol: str = "incident-workflow-v1"
    stage: Literal["baseline", "offline", "shadow", "canary"]
    executor: Literal["reference", "n8n"]
    scope: Literal["fixture"] = "fixture"
    provenance: Literal["synthetic", "gateway-observation"] = "synthetic"
    observed_at: str
    window: str
    observations: int = Field(ge=0)
    candidate_observations: int = Field(ge=0)
    baseline_observations: int = Field(ge=0)
    candidate_failures: int = Field(ge=0)
    baseline_failures: int = Field(ge=0)
    coverage: list[str] = Field(default_factory=list)
    passed: bool
    artifacts_digest: str
    dataset_digest: str
    candidate_mean_latency_ms: float = Field(default=0, ge=0)
    candidate_mean_cost_usd: float | None = Field(default=None, ge=0)
    production_authorized: Literal[False] = False
