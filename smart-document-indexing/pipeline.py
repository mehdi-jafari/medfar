"""Orchestrates the 5-step document indexing pipeline."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from extract import extract_text
from llm_client import LLMClient, LLMStepResult
from schema import (
    CONFIDENCE_REVIEW_THRESHOLD,
    MYLE_TAXONOMY,
    PatientIdentifiers,
    PipelineOutput,
    evidence_to_source_evidence,
    is_valid_class_subclass,
)
from validators import finalize_output, sanitize_physicians

logger = logging.getLogger(__name__)

MIXED_DOC_KEYWORDS = (
    "multiple document",
    "mixed document",
    "different document types",
    "more than one document",
    "page 1",
    "page 2",
    "referral declined",
    "parenteral iron",
)

STEP_TITLES = {
    "01_ocr_cleanup": "Step 1 — OCR Cleanup",
    "02_evidence_extraction": "Step 2 — Evidence Extraction",
    "03_entity_extraction": "Step 3 — Entity Extraction",
    "04_taxonomy_classification": "Step 4 — Taxonomy Classification",
    "05_validation": "Step 5 — Validation",
}


@dataclass
class PipelineStepResult:
    """One LLM pipeline step with display metadata."""

    step_number: int
    prompt_name: str
    title: str
    filled_prompt: str
    output: str | dict[str, Any]
    tokens_used: int
    latency_s: float


@dataclass
class PipelineRunResult:
    """Full pipeline run including intermediate step outputs."""

    document_id: str
    document_path: str
    raw_text: str
    steps: list[PipelineStepResult] = field(default_factory=list)
    final_output: PipelineOutput | None = None
    total_tokens: int = 0
    total_latency_s: float = 0.0


def _step_from_llm(step_number: int, llm_result: LLMStepResult) -> PipelineStepResult:
    return PipelineStepResult(
        step_number=step_number,
        prompt_name=llm_result.prompt_name,
        title=STEP_TITLES.get(llm_result.prompt_name, llm_result.prompt_name),
        filled_prompt=llm_result.filled_prompt,
        output=llm_result.output,
        tokens_used=llm_result.tokens_used,
        latency_s=llm_result.latency_s,
    )


def _normalize_other(values: Any) -> list[str]:
    if not values:
        return []
    items = values if isinstance(values, list) else [values]
    normalized: list[str] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, dict):
            normalized.append(json.dumps(item, ensure_ascii=False))
        else:
            normalized.append(str(item))
    return normalized


def _coerce_patient_field(value: Any) -> tuple[str | None, list[str]]:
    """Normalize LLM patient field values; lists go to primary + other."""
    if value is None:
        return None, []
    if isinstance(value, list):
        items = [str(v).strip() for v in value if v]
        if not items:
            return None, []
        return items[0], items[1:]
    text = str(value).strip()
    return (text or None), []


def merge(
    classification: dict[str, Any],
    entities: dict[str, Any],
    evidence: dict[str, Any],
    document_id: str,
) -> tuple[PipelineOutput, list[str]]:
    """Combine step outputs into final pipeline JSON. Returns (output, pre-validation warnings)."""
    patient_raw = entities.get("patient_identifiers", {})
    phone, phone_extra = _coerce_patient_field(patient_raw.get("phone"))
    other = _normalize_other(patient_raw.get("other"))
    other.extend(phone_extra)

    patient = PatientIdentifiers(
        name=patient_raw.get("name"),
        date_of_birth=patient_raw.get("date_of_birth"),
        health_card_number=patient_raw.get("health_card_number"),
        mrn=patient_raw.get("mrn"),
        phone=phone,
        address=patient_raw.get("address"),
        other=other,
    )

    ambiguities: list[str] = []
    ambiguities.extend(entities.get("ambiguities") or [])
    for alt in classification.get("alternative_classifications") or []:
        ambiguities.append(f"Alternative classification: {alt}")

    document_class = str(classification.get("document_class", "")).strip()
    document_subclass = str(classification.get("document_subclass", "")).strip()
    confidence = float(classification.get("classification_confidence", 0.0) or 0.0)

    human_review = bool(classification.get("human_review_required"))
    if not is_valid_class_subclass(document_class, document_subclass):
        human_review = True
        ambiguities.append(
            f"Invalid taxonomy pair: {document_class} / {document_subclass}"
        )
    if confidence < CONFIDENCE_REVIEW_THRESHOLD:
        human_review = True
        ambiguities.append(
            f"Low classification confidence ({confidence:.2f})"
        )
    if _looks_like_mixed_document(evidence, classification):
        human_review = True
        ambiguities.append(
            "Document may contain multiple document types across pages"
        )

    physicians, physician_warnings, physician_ambiguities = sanitize_physicians(
        entities.get("physicians") or []
    )
    ambiguities.extend(physician_ambiguities)
    if physician_warnings:
        human_review = True

    output = PipelineOutput(
        document_id=document_id,
        document_class=document_class,
        document_subclass=document_subclass,
        classification_confidence=confidence,
        short_description=str(classification.get("short_description", "")).strip(),
        patient_identifiers=patient,
        physicians=physicians,
        routing_support_text=str(
            classification.get("routing_support_text", "")
        ).strip(),
        ambiguities=sorted(set(ambiguities)),
        human_review_required=human_review,
        source_evidence=evidence_to_source_evidence(evidence),
    )
    return output, physician_warnings


def _apply_validation(
    final_output: PipelineOutput,
    validation: dict[str, Any],
    cleaned_text: str,
    pre_warnings: list[str] | None = None,
) -> PipelineOutput:
    final_output.validation_notes = list(validation.get("validation_notes") or [])
    if validation.get("human_review_required"):
        final_output.human_review_required = True

    return finalize_output(
        final_output,
        cleaned_text,
        llm_validation=validation,
        extra_warnings=pre_warnings,
    )


def _looks_like_mixed_document(
    evidence: dict[str, Any], classification: dict[str, Any]
) -> bool:
    """Heuristic: multiple document types in one PDF."""
    reasoning = str(classification.get("classification_reasoning", "")).lower()
    if any(keyword in reasoning for keyword in MIXED_DOC_KEYWORDS):
        return True

    purpose_clues = " ".join(
        (evidence.get("document_purpose_clues") or [])
        + (evidence.get("document_type_clues") or [])
    ).lower()
    if "declined" in purpose_clues and (
        "medication" in purpose_clues or "form" in purpose_clues or "iron" in purpose_clues
    ):
        return True

    admin = evidence.get("appointment_or_administrative_clues", [])
    meds = evidence.get("medication_clues", [])
    forms = evidence.get("form_or_report_clues", [])
    if admin and (meds or forms):
        return True

    return bool(classification.get("human_review_required"))


def run_pipeline_detailed(
    file_path: str | Path, llm: LLMClient | None = None
) -> PipelineRunResult:
    """Run the full pipeline and return intermediate step outputs."""
    path = Path(file_path)
    client = llm or LLMClient()
    document_id = path.stem
    tokens_before = client.total_tokens
    started_steps: list[PipelineStepResult] = []

    logger.info("Extracting text from %s", path.name)
    raw_text = extract_text(path)

    logger.info("Step 1: OCR cleanup")
    step1 = client.run_detailed("01_ocr_cleanup", raw_ocr_text=raw_text)
    started_steps.append(_step_from_llm(1, step1))
    cleaned = step1.output
    if not isinstance(cleaned, str):
        raise TypeError("OCR cleanup step must return text")

    logger.info("Step 2: Evidence extraction")
    step2 = client.run_detailed(
        "02_evidence_extraction", cleaned_document_text=cleaned
    )
    started_steps.append(_step_from_llm(2, step2))
    evidence = step2.output
    if not isinstance(evidence, dict):
        raise TypeError("Evidence extraction must return JSON")

    logger.info("Step 3: Entity extraction")
    step3 = client.run_detailed(
        "03_entity_extraction", cleaned_document_text=cleaned
    )
    started_steps.append(_step_from_llm(3, step3))
    entities = step3.output
    if not isinstance(entities, dict):
        raise TypeError("Entity extraction must return JSON")

    logger.info("Step 4: Taxonomy classification")
    step4 = client.run_detailed(
        "04_taxonomy_classification",
        cleaned_document_text=cleaned,
        evidence_json=json.dumps(evidence, ensure_ascii=False),
        taxonomy=json.dumps(MYLE_TAXONOMY, ensure_ascii=False),
    )
    started_steps.append(_step_from_llm(4, step4))
    classification = step4.output
    if not isinstance(classification, dict):
        raise TypeError("Classification must return JSON")

    final_output, physician_warnings = merge(
        classification, entities, evidence, document_id=document_id
    )

    logger.info("Step 5: Validation")
    step5 = client.run_detailed(
        "05_validation",
        cleaned_document_text=cleaned,
        pipeline_output_json=final_output.model_dump_json(),
    )
    started_steps.append(_step_from_llm(5, step5))
    validation = step5.output
    if not isinstance(validation, dict):
        raise TypeError("Validation must return JSON")

    final_output = _apply_validation(
        final_output, validation, cleaned, pre_warnings=physician_warnings
    )
    total_latency = sum(step.latency_s for step in started_steps)

    return PipelineRunResult(
        document_id=document_id,
        document_path=str(path),
        raw_text=raw_text,
        steps=started_steps,
        final_output=final_output,
        total_tokens=client.total_tokens - tokens_before,
        total_latency_s=total_latency,
    )


def run_pipeline(file_path: str | Path, llm: LLMClient | None = None) -> PipelineOutput:
    """Run the full indexing pipeline on a single PDF."""
    result = run_pipeline_detailed(file_path, llm=llm)
    if result.final_output is None:
        raise RuntimeError("Pipeline completed without final output")
    return result.final_output


def save_output(output: PipelineOutput, outputs_dir: str | Path) -> Path:
    """Write pipeline output JSON to the outputs directory."""
    out_dir = Path(outputs_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{output.document_id}.json"
    out_path.write_text(
        output.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return out_path
