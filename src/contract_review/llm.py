import os
import time

from typing import Any

from openai import OpenAI


DEFAULT_TEMPERATURE = 0
DEFAULT_SEED = 42
DEFAULT_MAX_TOKENS = 1024


def get_generation_settings() -> dict[str, Any]:
    return {
        "temperature": DEFAULT_TEMPERATURE,
        "seed": DEFAULT_SEED,
        "max_tokens": DEFAULT_MAX_TOKENS,
    }


def call_llm(
    messages: list[dict[str, str]],
    response_schema: dict[str, Any],
    max_tokens_override: int | None = None,
) -> dict[str, Any]:

    client = OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.getenv("LLM_API_KEY", "unused"),
        max_retries=0,
    )

    model = os.environ["LLM_MODEL"]

    generation_settings = get_generation_settings()

    if max_tokens_override is not None:
    	if max_tokens_override <= 0:
        	raise ValueError("max_tokens_override must be positive")

    	generation_settings = {
        	**generation_settings,
        	"max_tokens": max_tokens_override,
    	}

    start = time.perf_counter()

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=generation_settings["temperature"],
        seed=generation_settings["seed"],
        max_tokens=generation_settings["max_tokens"],
        extra_body={
            "structured_outputs": {
                "json": response_schema,
            }
        },
    )

    latency_ms = round(
        (time.perf_counter() - start) * 1000,
        2,
    )

    usage = response.usage

    choice = response.choices[0]

    return {
        "content": choice.message.content,
        "model": response.model,
        "prompt_tokens": (
            usage.prompt_tokens if usage else None
        ),
        "completion_tokens": (
            usage.completion_tokens if usage else None
        ),
        "total_tokens": (
            usage.total_tokens if usage else None
        ),
        "latency_ms": latency_ms,
        "request_id": getattr(
            response,
            "_request_id",
            None,
        ),
        "finish_reason": choice.finish_reason,
        "generation_settings": generation_settings,
    }
