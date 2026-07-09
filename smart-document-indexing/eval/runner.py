"""Step-by-step pipeline runner for the eval UI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from extract import extract_text
from llm_client import LLMClient
from pipeline import (
    PipelineRunResult,
    PipelineStepResult,
    _apply_validation,
    _step_from_llm,
    merge,
)
from schema import MYLE_TAXONOMY, PipelineOutput

STEP_FLOW = [
    {"number": 0, "key": "extract", "title": "PDF Text Extraction", "llm": False},
    {"number": 1, "key": "01_ocr_cleanup", "title": "OCR Cleanup", "llm": True},
    {"number": 2, "key": "02_evidence_extraction", "title": "Evidence Extraction", "llm": True},
    {"number": 3, "key": "03_entity_extraction", "title": "Entity Extraction", "llm": True},
    {"number": 4, "key": "04_taxonomy_classification", "title": "Taxonomy Classification", "llm": True},
    {"number": 5, "key": "05_validation", "title": "Validation", "llm": True},
]


@dataclass
class InteractivePipelineState:
    """Mutable pipeline state for step-by-step UI execution."""

    document_id: str
    document_path: str
    raw_text: str | None = None
    cleaned: str | None = None
    evidence: dict[str, Any] | None = None
    entities: dict[str, Any] | None = None
    classification: dict[str, Any] | None = None
    final_output: PipelineOutput | None = None
    pending_warnings: list[str] = field(default_factory=list)
    steps: list[PipelineStepResult] = field(default_factory=list)
    completed_through: int = -1
    total_tokens: int = 0
    total_latency_s: float = 0.0
    error: str | None = None

    @property
    def next_step_number(self) -> int:
        return self.completed_through + 1

    @property
    def is_complete(self) -> bool:
        return self.completed_through >= 5

    def to_run_result(self) -> PipelineRunResult:
        return PipelineRunResult(
            document_id=self.document_id,
            document_path=self.document_path,
            raw_text=self.raw_text or "",
            steps=self.steps,
            final_output=self.final_output,
            total_tokens=self.total_tokens,
            total_latency_s=self.total_latency_s,
        )


def new_state(pdf_path: str | Path) -> InteractivePipelineState:
    path = Path(pdf_path)
    return InteractivePipelineState(
        document_id=path.stem,
        document_path=str(path),
    )


def get_step_info(step_number: int) -> dict[str, Any]:
    for step in STEP_FLOW:
        if step["number"] == step_number:
            return step
    raise ValueError(f"Unknown step number: {step_number}")


def run_step(
    state: InteractivePipelineState,
    step_number: int,
    llm: LLMClient,
) -> InteractivePipelineState:
    """Run a single pipeline step and update state."""
    if step_number != state.next_step_number:
        raise ValueError(
            f"Expected step {state.next_step_number}, got {step_number}. "
            "Complete prior steps first."
        )

    state.error = None
    tokens_before = llm.total_tokens

    try:
        if step_number == 0:
            state.raw_text = extract_text(state.document_path)
        elif step_number == 1:
            if not state.raw_text:
                raise RuntimeError("Raw text missing. Run extraction first.")
            result = llm.run_detailed(
                "01_ocr_cleanup", raw_ocr_text=state.raw_text
            )
            if not isinstance(result.output, str):
                raise TypeError("OCR cleanup must return text")
            state.cleaned = result.output
            state.steps.append(_step_from_llm(1, result))
            state.total_latency_s += result.latency_s
        elif step_number == 2:
            if not state.cleaned:
                raise RuntimeError("Cleaned text missing. Run step 1 first.")
            result = llm.run_detailed(
                "02_evidence_extraction", cleaned_document_text=state.cleaned
            )
            if not isinstance(result.output, dict):
                raise TypeError("Evidence extraction must return JSON")
            state.evidence = result.output
            state.steps.append(_step_from_llm(2, result))
            state.total_latency_s += result.latency_s
        elif step_number == 3:
            if not state.cleaned:
                raise RuntimeError("Cleaned text missing. Run step 1 first.")
            result = llm.run_detailed(
                "03_entity_extraction", cleaned_document_text=state.cleaned
            )
            if not isinstance(result.output, dict):
                raise TypeError("Entity extraction must return JSON")
            state.entities = result.output
            state.steps.append(_step_from_llm(3, result))
            state.total_latency_s += result.latency_s
        elif step_number == 4:
            if not state.cleaned or state.evidence is None:
                raise RuntimeError("Need cleaned text and evidence before classification.")
            result = llm.run_detailed(
                "04_taxonomy_classification",
                cleaned_document_text=state.cleaned,
                evidence_json=json.dumps(state.evidence, ensure_ascii=False),
                taxonomy=json.dumps(MYLE_TAXONOMY, ensure_ascii=False),
            )
            if not isinstance(result.output, dict):
                raise TypeError("Classification must return JSON")
            state.classification = result.output
            state.steps.append(_step_from_llm(4, result))
            state.total_latency_s += result.latency_s
            state.final_output, state.pending_warnings = merge(
                state.classification,
                state.entities or {},
                state.evidence,
                document_id=state.document_id,
            )
        elif step_number == 5:
            if not state.cleaned or state.final_output is None:
                raise RuntimeError("Need cleaned text and merged output before validation.")
            result = llm.run_detailed(
                "05_validation",
                cleaned_document_text=state.cleaned,
                pipeline_output_json=state.final_output.model_dump_json(),
            )
            if not isinstance(result.output, dict):
                raise TypeError("Validation must return JSON")
            state.steps.append(_step_from_llm(5, result))
            state.total_latency_s += result.latency_s
            state.final_output = _apply_validation(
                state.final_output,
                result.output,
                state.cleaned,
                pre_warnings=state.pending_warnings,
            )
        else:
            raise ValueError(f"Unsupported step: {step_number}")

        state.completed_through = step_number
        if step_number > 0:
            state.total_tokens += llm.total_tokens - tokens_before

    except Exception as exc:
        state.error = str(exc)
        raise

    return state


def preview_prompt(state: InteractivePipelineState, step_number: int, llm: LLMClient) -> str:
    """Return the filled prompt for a step without calling the model."""
    if step_number == 0:
        return (
            "Local PDF extraction using pymupdf → Tesseract OCR → GPT-4o vision fallback.\n"
            f"File: {state.document_path}"
        )
    if step_number == 1:
        if not state.raw_text:
            return "Run PDF text extraction first to preview this prompt."
        return llm.prepare_prompt("01_ocr_cleanup", raw_ocr_text=state.raw_text)
    if step_number == 2:
        if not state.cleaned:
            return "Run step 1 first to preview this prompt."
        return llm.prepare_prompt(
            "02_evidence_extraction", cleaned_document_text=state.cleaned
        )
    if step_number == 3:
        if not state.cleaned:
            return "Run step 1 first to preview this prompt."
        return llm.prepare_prompt(
            "03_entity_extraction", cleaned_document_text=state.cleaned
        )
    if step_number == 4:
        if not state.cleaned or state.evidence is None:
            return "Run steps 1–2 first to preview this prompt."
        return llm.prepare_prompt(
            "04_taxonomy_classification",
            cleaned_document_text=state.cleaned,
            evidence_json=json.dumps(state.evidence, ensure_ascii=False),
            taxonomy=json.dumps(MYLE_TAXONOMY, ensure_ascii=False),
        )
    if step_number == 5:
        if not state.cleaned or state.final_output is None:
            return "Run steps 1–4 first to preview this prompt."
        return llm.prepare_prompt(
            "05_validation",
            cleaned_document_text=state.cleaned,
            pipeline_output_json=state.final_output.model_dump_json(),
        )
    return ""
