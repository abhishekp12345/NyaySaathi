"""Model-agnostic LLM wrapper using LiteLLM with retries and JSON parsing."""

from __future__ import annotations

import json
import os
import time
import logging
from typing import Any, Optional, Type
from pathlib import Path

# Automatically load environment variables from .env file if present
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

from pydantic import BaseModel, ValidationError
import litellm

# Disable remote telemetry and remote cost map fetching to prevent startup hangs
litellm.telemetry = False
litellm.suppress_debug_info = True
os.environ["LITELLM_LOCAL_RESOURCES"] = "True"

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

def get_model() -> str:
    if os.environ.get("GROQ_API_KEY"):
        return os.environ.get("LLM_MODEL", "groq/qwen/qwen3.8-27b")
    return os.environ.get("LLM_MODEL", "gemini/gemini-1.5-flash")


# ── Retry with exponential backoff ───────────────────────────────────────────

MAX_RETRIES = 3

def _backoff_delay(attempt: int) -> float:
    return float(min(1.5 + attempt * 1.0, 5.0))


# ── Core completion function ─────────────────────────────────────────────────

FALLBACK_MODELS = [
    "gemini/gemini-1.5-flash",
    "gemini/gemini-2.0-flash",
]

GROQ_FALLBACK_MODELS = [
    "groq/openai/gpt-oss-120b",
    "groq/openai/gpt-oss-20b",
]

def chat(
    messages: list[dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 1500,
    response_format: Optional[dict] = None,
) -> str:
    """Send messages to the configured LLM and return the text response.

    Handles HTTP 429 with intelligent backoff and fallback models.
    """
    configured_model = get_model()
    is_groq = "groq" in configured_model.lower()

    if is_groq:
        models_to_try = [configured_model] + [m for m in GROQ_FALLBACK_MODELS if m != configured_model]
    else:
        models_to_try = [configured_model] + [m for m in FALLBACK_MODELS if m != configured_model]

    last_error = None
    for model in models_to_try:
        for attempt in range(3):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if response_format:
                    kwargs["response_format"] = response_format

                response = litellm.completion(**kwargs)
                content = response.choices[0].message.content
                return content.strip() if content else ""

            except (litellm.RateLimitError, litellm.ServiceUnavailableError) as e:
                last_error = e
                if attempt < 2:
                    delay = float(1.0 + attempt * 1.0)
                    logger.warning(f"Transient rate limit on {model}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.info(f"Flipping to fallback model after rate limit on {model}")
                    break
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if ("429" in err_str or "rate limit" in err_str or "503" in err_str) and attempt < 2:
                    delay = float(1.0 + attempt * 1.0)
                    logger.warning(f"Transient error on {model}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    break

    if is_groq:
        raise RuntimeError("Groq API rate limit reached. Please wait 3-5 seconds and resend your message.")
    else:
        raise RuntimeError(f"Service temporarily busy ({type(last_error).__name__ if last_error else 'Unknown'}). Please retry shortly.")


# ── JSON completion with Pydantic validation ─────────────────────────────────

def chat_json(
    messages: list[dict[str, str]],
    schema: Type[BaseModel],
    temperature: float = 0.2,
    max_tokens: int = 1500,
) -> BaseModel:
    """Chat with the LLM and parse the output as a Pydantic model.

    Uses JSON mode where supported; otherwise parses raw text.
    Retries once on validation failure with a correction prompt.
    """
    # Try with JSON mode first
    try:
        raw = chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
    except Exception:
        # Fallback: no response_format
        raw = chat(messages, temperature=temperature, max_tokens=max_tokens)

    # Parse JSON from the response
    parsed = _extract_json(raw)
    if parsed is None:
        # Retry once with a correction prompt
        messages_retry = messages + [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON. "
                    "Please respond with ONLY a valid JSON object matching this schema:\n"
                    f"{schema.model_json_schema()}"
                ),
            },
        ]
        raw = chat(messages_retry, temperature=0.1, max_tokens=max_tokens)
        parsed = _extract_json(raw)
        if parsed is None:
            raise ValueError(f"Could not parse JSON from LLM response after retry:\n{raw[:500]}")

    # Validate with Pydantic
    try:
        return schema.model_validate(parsed)
    except ValidationError:
        # One more retry with explicit schema
        messages_retry = messages + [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    f"Your JSON did not match the required schema. "
                    f"Please output valid JSON matching:\n{schema.model_json_schema()}"
                ),
            },
        ]
        raw = chat(messages_retry, temperature=0.1, max_tokens=max_tokens)
        parsed = _extract_json(raw)
        if parsed is None:
            raise ValueError("JSON parse failure after schema correction retry")
        return schema.model_validate(parsed)


def _extract_json(text: str) -> Optional[dict]:
    """Extract a JSON object from LLM text, handling markdown code fences."""
    text = text.strip()

    # Remove markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines if they're fences
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    start = text.find("{")
    if start == -1:
        return None

    # Find matching closing brace
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ── Audio-capable chat (for voice input via Gemini) ──────────────────────────

def chat_with_audio(
    messages: list[dict[str, str]],
    audio_data: Optional[bytes] = None,
    audio_mime: str = "audio/wav",
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> str:
    """Chat with an audio input (Gemini natively handles audio).

    For non-Gemini models, the caller should use stt.py to transcribe first.
    """
    model = get_model()

    if audio_data and "gemini" in model.lower():
        import base64
        b64 = base64.b64encode(audio_data).decode("utf-8")
        multimodal_messages = messages[:-1] + [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": messages[-1]["content"] if messages else "Transcribe this audio and respond."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{audio_mime};base64,{b64}",
                        },
                    },
                ],
            }
        ]
        return chat(
            multimodal_messages, temperature=temperature, max_tokens=max_tokens
        )
    else:
        raise ValueError(
            f"Native audio input is not supported for model {model}. "
            "Use stt.transcribe(audio_bytes) with Groq Whisper instead."
        )
