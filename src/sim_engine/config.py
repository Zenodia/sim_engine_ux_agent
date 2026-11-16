"""Inference configuration. Credentials never appear in reprs or public metadata."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_BASE_URL = "https://inference-api.nvidia.com/v1"
DEFAULT_MODEL = "aws/anthropic/bedrock-claude-sonnet-5"
DEFAULT_SDG_MODEL = "nvidia/nvidia/nemotron-3-super-rc-nim"


def load_environment(path: Path | None = None) -> None:
    """Load the working directory's .env; exported shell settings take precedence."""
    load_dotenv(dotenv_path=path if path is not None else Path.cwd() / ".env", override=False)


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    timeout: float = 90
    max_tokens: int = 512
    response_format: str = "text"
    temperature: float | None = None
    enable_thinking: bool | None = None

    def public_metadata(self) -> dict:
        # No client, headers, endpoint URL/query, or credential values are serialized.
        return {"model": self.model, "max_tokens": self.max_tokens,
                "response_format": self.response_format, "temperature": self.temperature,
                "timeout_seconds": self.timeout, "transport": "openai-sdk",
                "enable_thinking": self.enable_thinking}


def llm_settings(variant: str = "candidate") -> LLMSettings:
    load_environment()

    def value(suffix: str, default: str | None = None) -> str | None:
        names = [f"SIM_{variant.upper()}_LLM_{suffix}"]
        if variant != "sdg" or suffix in ("BASE_URL", "API_KEY", "TIMEOUT"):
            names.append(f"SIM_LLM_{suffix}")
        for name in names:
            item = os.getenv(name)
            if item is not None and item.strip():
                return item.strip()
        return default

    api_key = value("API_KEY") or next((os.environ[name].strip() for name in
        ("NVIDIA_API_KEY", "INFERENCE_API_KEY", "OPENAI_API_KEY")
        if os.getenv(name, "").strip()), "")
    if not api_key or api_key in ("replace-me", "your-nvapikey"):
        raise ValueError("Set SIM_LLM_API_KEY in .env or export a supported API-key variable")
    temperature = value("TEMPERATURE")
    model = value("MODEL", DEFAULT_SDG_MODEL if variant == "sdg" else DEFAULT_MODEL)
    thinking = value("ENABLE_THINKING", "false" if variant == "sdg" and "nemotron" in model else None)
    if thinking is not None and thinking.lower() not in ("true", "false"):
        raise ValueError("Inference ENABLE_THINKING must be true or false")
    settings = LLMSettings(
        base_url=value("BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        model=model, api_key=api_key,
        timeout=float(value("TIMEOUT", "90")),
        max_tokens=int(value("MAX_TOKENS", "1024" if variant == "sdg" else "512")),
        response_format=value("RESPONSE_FORMAT", "text"),
        temperature=float(temperature) if temperature is not None else (0.7 if variant == "sdg" else None),
        enable_thinking=thinking.lower() == "true" if thinking is not None else None,
    )
    if settings.max_tokens <= 0 or settings.timeout <= 0:
        raise ValueError("Inference token limit and timeout must be positive")
    if settings.response_format not in ("text", "json_object"):
        raise ValueError("SIM_LLM_RESPONSE_FORMAT must be text or json_object")
    return settings
