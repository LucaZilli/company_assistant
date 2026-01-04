from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import typing as t

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import instructor
from openai import OpenAI

from config import OPENROUTER_API_KEY
from config import OPENROUTER_BASE_URL


@dataclass
class LLMResponse:
    """Minimal response wrapper to keep call sites consistent."""

    content: str
    completion: object


class SimpleLLM:
    """Small wrapper around OpenAI-compatible chat completions."""

    def __init__(self, model_name: str, temperature: float = 0.0) -> None:
        """Initialize the LLM wrapper.

        Args:
            model_name: Model identifier to use for completions.
            temperature: Sampling temperature for the model.
        """
        self.model_name = model_name
        self.temperature = temperature
        self.client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
        )

    def invoke(self, messages: list[dict[str, t.Any]]) -> LLMResponse:
        """Call the chat completion API.

        Args:
            messages: Chat messages in OpenAI format.

        Returns:
            An LLMResponse wrapper containing text and raw completion.
        """
        completion = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=self.temperature,
        )
        content = completion.choices[0].message.content or ''
        return LLMResponse(content=content, completion=completion)


def get_llm(model_name: str, temperature: float = 0.0) -> SimpleLLM:
    """Get a configured OpenAI-compatible LLM instance.

    Args:
        model_name: Model identifier.
        temperature: Sampling temperature for the model.

    Returns:
        A configured SimpleLLM instance.
    """
    return SimpleLLM(model_name=model_name, temperature=temperature)


def get_instructor_client() -> instructor.Instructor:
    """Get an Instructor client for structured outputs.

    Returns:
        An Instructor-wrapped OpenAI client.
    """
    return instructor.from_openai(
        OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
        )
    )
