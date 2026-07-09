"""Orchestrates the 5-step document indexing pipeline."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from extract import extract_text
from llm_client import LLMClient
from schema import (
    MYLE_TAXONOMY,
    PatientIdentifiers,
    Physician,
    PhysicianRole,
    PipelineOutput,
    evidence_to_source_evidence,
    is_valid_class_subclass,
)

logger = logging.getLogger(__name__)

CONFIDENCE_REVIEW_THRESHOLD = 0.6
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


def _parse_physicians(raw_physicians: list[dict[str, Any]]) -> list[Physician]:
    physicians: list[Physician] = []
    for item in raw_physicians:
        role_raw = str(item.get("role", "unknown")).lower().strip()
        try:
            role = PhysicianRole(role_raw)
        except ValueError:
            role = PhysicianRole.UNKNOWN
        physicians.append(
            Physician(
                name=str(item.get("name", "")).strip(),
                role=role,
                confidence=float(item.get("confidence", 0.0) or 0.0),
                evidence=str(item.get("evidence", "")).strip(),
            )
        )
    return [p for p in physicians if p.name]


def _looks_like_mixed_document(
    evidence: dict[str, Any], classification: dict[str, Any]
) -> bool:
    """Heuristic: multiple document types in one PDF."""
    reasoning = str(classification.get("classification_reasoning", "")).lower()
    if any(keyword in reasoning for keyword in MIXED_DOC_KEYWORDS):
        return True

    purpose_clues = " ".join(evidence.get("document_purpose_clues", [])).lower()
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


def merge(
    classification: dict[str, Any],
    entities: dict[str, Any],
    evidence: dict[str, Any],
    document_id: str,
) -> PipelineOutput:
    """Combine step outputs into final pipeline JSON."""
    patient_raw = entities.get("patient_identifiers", {})
    patient = PatientIdentifiers(
        name=patient_raw.get("name"),
        date_of_birth=patient_raw.get("date_of_birth"),
        health_card_number=patient_raw.get("health_card_number"),
        mrn=patient_raw.get("mrn"),
        phone=patient_raw.get("phone"),
        address=patient_raw.get("address"),
        other=patient_raw.get("other") or [],
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

    return PipelineOutput(
        document_id=document_id,
        document_class=document_class,
        document_subclass=document_subclass,
        classification_confidence=confidence,
        short_description=str(classification.get("short_description", "")).strip(),
        patient_identifiers=patient,
        physicians=_parse_physicians(entities.get("physicians") or []),
        routing_support_text=str(
            classification.get("routing_support_text", "")
        ).strip(),
        ambiguities=sorted(set(ambiguities)),
        human_review_required=human_review,
        source_evidence=evidence_to_source_evidence(evidence),
    )


def run_pipeline(file_path: str | Path, llm: LLMClient | None = None) -> PipelineOutput:
    """Run the full indexing pipeline on a single PDF."""
    path = Path(file_path)
    client = llm or LLMClient()
    document_id = path.stem

    logger.info("Extracting text from %s", path.name)
    raw_text = extract_text(path)

    logger.info("Step 1: OCR cleanup")
    cleaned = client.run("01_ocr_cleanup", raw_ocr_text=raw_text)
    if not isinstance(cleaned, str):
        raise TypeError("OCR cleanup step must return text")

    logger.info("Step 2: Evidence extraction")
    evidence = client.run("02_evidence_extraction", cleaned_document_text=cleaned)
    if not isinstance(evidence, dict):
        raise TypeError("Evidence extraction must return JSON")

    logger.info("Step 3: Entity extraction")
    entities = client.run("03_entity_extraction", cleaned_document_text=cleaned)
    if not isinstance(entities, dict):
        raise TypeError("Entity extraction must return JSON")

    logger.info("Step 4: Taxonomy classification")
    classification = client.run(
        "04_taxonomy_classification",
        cleaned_document_text=cleaned,
        evidence_json=json.dumps(evidence, ensure_ascii=False),
        taxonomy=json.dumps(MYLE_TAXONOMY, ensure_ascii=False),
    )
    if not isinstance(classification, dict):
        raise TypeError("Classification must return JSON")

    final_output = merge(classification, entities, evidence, document_id=document_id)

    logger.info("Step 5: Validation")
    validation = client.run(
        "05_validation",
        cleaned_document_text=cleaned,
        pipeline_output_json=final_output.model_dump_json(),
    )
    if not isinstance(validation, dict):
        raise TypeError("Validation must return JSON")

    final_output.validation_notes = list(validation.get("validation_notes") or [])
    recommended = validation.get("recommended_changes") or []
    for note in recommended:
        final_output.validation_notes.append(f"Recommended: {note}")

    if validation.get("human_review_required"):
        final_output.human_review_required = True

    if not validation.get("is_valid", True):
        final_output.human_review_required = True
        final_output.validation_notes.append("Validation flagged output as invalid")

    return final_output


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
