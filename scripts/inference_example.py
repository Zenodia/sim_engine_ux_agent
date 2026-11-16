"""Manual smoke example for the NVIDIA endpoint; executes only when you run it."""
from openai import OpenAI

from sim_engine.config import llm_settings


def main() -> None:
    settings = llm_settings()
    with OpenAI(api_key=settings.api_key, base_url=settings.base_url,
                timeout=settings.timeout, max_retries=0) as client:
        response = client.chat.completions.create(
            model=settings.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Summarize how AI assistants can help software teams triage incidents."},
            ],
            max_tokens=settings.max_tokens,
        )
        print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
