"""Mocked inference boundaries for optional manual execution; no live API calls."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from sim_engine import config
from sim_engine.agents import OpenAICompatible
from sim_engine.evidence import Journal


@pytest.fixture
def inference_env(monkeypatch):
    # Tests never read the operator's real .env or inherit inference overrides.
    monkeypatch.setattr(config, "load_environment", lambda: None)
    for key in list(config.os.environ):
        if (key.startswith("SIM_LLM_") or key.startswith("SIM_BASELINE_LLM_") or
                key.startswith("SIM_CANDIDATE_LLM_") or key.startswith("SIM_SDG_LLM_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("SIM_LLM_API_KEY", "test-key-never-a-real-secret")


def test_nvidia_defaults_and_variant_precedence(inference_env, monkeypatch):
    shared = config.llm_settings()
    assert shared.base_url == "https://inference-api.nvidia.com/v1"
    assert shared.model == "aws/anthropic/bedrock-claude-sonnet-5"
    assert shared.max_tokens == 512
    monkeypatch.setenv("SIM_CANDIDATE_LLM_MODEL", "candidate-model")
    assert config.llm_settings("candidate").model == "candidate-model"
    assert config.llm_settings("baseline").model == shared.model
    assert "test-key-never-a-real-secret" not in repr(shared)
    assert "api_key" not in shared.public_metadata()


def test_sdg_has_separate_model_and_generation_settings(inference_env, monkeypatch):
    monkeypatch.setenv("SIM_LLM_MODEL", "agent-model")
    monkeypatch.setenv("SIM_LLM_MAX_TOKENS", "512")
    settings = config.llm_settings("sdg")
    assert settings.model == "nvidia/nvidia/nemotron-3-super-rc-nim"
    assert settings.temperature == 0.7
    assert settings.max_tokens == 1024
    assert settings.enable_thinking is False
    assert settings.api_key == config.llm_settings("candidate").api_key


def test_dotenv_preserves_exported_values(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("SIM_LLM_MODEL=file-model\nSIM_LLM_MAX_TOKENS=1024\n", encoding="utf-8")
    monkeypatch.setenv("SIM_LLM_MODEL", "exported-model")
    monkeypatch.delenv("SIM_LLM_MAX_TOKENS", raising=False)
    config.load_environment(path)
    assert config.os.environ["SIM_LLM_MODEL"] == "exported-model"
    assert config.os.environ["SIM_LLM_MAX_TOKENS"] == "1024"
    monkeypatch.delenv("SIM_LLM_MAX_TOKENS")


def test_sdk_request_and_journal_exclude_credentials(inference_env, monkeypatch, tmp_path):
    import openai

    content = '```json\n{"tool":"finish","args":{"status":"remembered","message":"Saved."}}\n```'
    message = SimpleNamespace(content=content, model_dump=lambda **kwargs: {"content": content})
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=SimpleNamespace(model_dump=lambda **kwargs: {"prompt_tokens": 12, "completion_tokens": 8}),
    )
    create = AsyncMock(return_value=response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=AsyncMock())
    factory = Mock(return_value=client)
    monkeypatch.setattr(openai, "AsyncOpenAI", factory)
    journal = Journal(tmp_path / "events.jsonl")
    backend = OpenAICompatible(journal, "candidate")

    async def exercise():
        try:
            return await backend.decide({"session": 1}, [{"role": "user", "content": "Remember chat."}])
        finally:
            await backend.close()

    action = asyncio.run(exercise())
    request = create.call_args.kwargs
    assert request["max_tokens"] == 512
    assert "response_format" not in request
    assert "temperature" not in request
    assert action.tool == "finish"
    assert backend.input_tokens == 12
    assert backend.output_tokens == 8
    client.close.assert_awaited_once()
    assert factory.call_args.kwargs["base_url"] == config.DEFAULT_BASE_URL
    assert "test-key-never-a-real-secret" not in journal.path.read_text(encoding="utf-8")
    for line in journal.path.read_text(encoding="utf-8").splitlines():
        json.loads(line)
