"""OpenAI client for loading prompt templates and running pipeline steps."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
JSON_PROMPTS = {
    "02_evidence_extraction",
    "03_entity_extraction",
    "04_taxonomy_classification",
    "05_validation",
}


@dataclass
class LLMStepResult:
    """Result of a single LLM prompt execution."""

    prompt_name: str
    filled_prompt: str
    output: str | dict[str, Any]
    tokens_used: int
    latency_s: float


class LLMClient:
    """Loads markdown prompts and calls OpenAI chat completions."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        prompts_dir: Path | None = None,
    ) -> None:
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        self.client = OpenAI(api_key=self.api_key)
        self.prompts_dir = prompts_dir or PROMPTS_DIR
        self.total_tokens = 0

    def _load_template(self, prompt_name: str) -> str:
        path = self.prompts_dir / f"{prompt_name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8")

    def _fill_template(self, template: str, variables: dict[str, str]) -> str:
        filled = template
        for key, value in variables.items():
            filled = filled.replace(f"{{{{{key}}}}}", value)
        unresolved = re.findall(r"\{\{(\w+)\}\}", filled)
        if unresolved:
            logger.warning("Unresolved template variables: %s", unresolved)
        return filled

    def _call_model(self, prompt: str, json_mode: bool) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**kwargs)
        if response.usage:
            self.total_tokens += response.usage.total_tokens

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from model")
        return content.strip()

    def prepare_prompt(self, prompt_name: str, **variables: str) -> str:
        """Load and fill a prompt template without calling the model."""
        template = self._load_template(prompt_name)
        return self._fill_template(template, {k: str(v) for k, v in variables.items()})

    def run_detailed(self, prompt_name: str, **variables: str) -> LLMStepResult:
        """Run a named prompt and return prompt text, output, and usage metadata."""
        filled = self.prepare_prompt(prompt_name, **variables)
        json_mode = prompt_name in JSON_PROMPTS
        tokens_before = self.total_tokens
        started = time.perf_counter()
        content = self._call_model(filled, json_mode=json_mode)
        latency_s = time.perf_counter() - started
        tokens_used = self.total_tokens - tokens_before

        if not json_mode:
            output: str | dict[str, Any] = content
        else:
            try:
                output = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON from prompt {prompt_name}: {content[:200]}"
                ) from exc

        return LLMStepResult(
            prompt_name=prompt_name,
            filled_prompt=filled,
            output=output,
            tokens_used=tokens_used,
            latency_s=latency_s,
        )

    def run(self, prompt_name: str, **variables: str) -> str | dict[str, Any]:
        """Run a named prompt. Returns text for step 01, dict for JSON steps."""
        return self.run_detailed(prompt_name, **variables).output
