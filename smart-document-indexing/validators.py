"""Deterministic pipeline validation checks."""

from __future__ import annotations

import re
from typing import Any

from schema import (
    CONFIDENCE_REVIEW_THRESHOLD,
    PipelineOutput,
    PipelineStatus,
    Physician,
    PhysicianRole,
    is_valid_class_subclass,
)

PHYSICIAN_PLACEHOLDER_NAMES = frozenset(
    name.lower()
    for name in (
        "Reading Physician",
        "Referring Physician",
        "Ordering Physician",
        "Attending Physician",
        "Consulting Physician",
        "Primary Physician",
        "Physician",
        "Doctor",
        "Unknown Physician",
        "Reading MD",
        "Referring MD",
    )
)

ROLE_LIKE_NAME_PREFIXES = (
    "reading ",
    "referring ",
    "ordering ",
    "attending ",
    "consulting ",
)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _fuzzy_in_text(needle: str, haystack: str) -> bool:
    if not needle or len(_normalize_text(needle)) < 4:
        return True
    return _normalize_text(needle) in _normalize_text(haystack)


def is_placeholder_physician_name(name: str) -> bool:
    """Return True when a physician name is a role label, not a person."""
    cleaned = name.strip()
    if not cleaned:
        return True
    lower = cleaned.lower()
    if lower in PHYSICIAN_PLACEHOLDER_NAMES:
        return True
    return any(lower.startswith(prefix) for prefix in ROLE_LIKE_NAME_PREFIXES)


def sanitize_physicians(
    raw_physicians: list[dict[str, Any]],
) -> tuple[list[Physician], list[str], list[str]]:
    """Reject placeholder physician names. Returns (physicians, warnings, ambiguities)."""
    physicians: list[Physician] = []
    warnings: list[str] = []
    ambiguities: list[str] = []

    for item in raw_physicians:
        name = str(item.get("name", "")).strip()
        if not name:
            continue

        role_raw = str(item.get("role", "unknown")).lower().strip()
        try:
            role = PhysicianRole(role_raw)
        except ValueError:
            role = PhysicianRole.UNKNOWN

        confidence = float(item.get("confidence", 0.0) or 0.0)
        evidence = str(item.get("evidence", "")).strip()

        if is_placeholder_physician_name(name):
            warnings.append(
                f"Physician placeholder rejected: '{name}' is a role label, not a person name"
            )
            ambiguities.append(
                f"No named physician available; document only references role label '{name}'"
            )
            continue

        physicians.append(
            Physician(
                name=name,
                role=role,
                confidence=confidence,
                evidence=evidence,
            )
        )

    return physicians, warnings, ambiguities


def _patient_fields(output: PipelineOutput) -> list[tuple[str, str]]:
    patient = output.patient_identifiers
    fields: list[tuple[str, str]] = []
    for field_name in (
        "name",
        "date_of_birth",
        "health_card_number",
        "mrn",
        "phone",
        "address",
    ):
        value = getattr(patient, field_name)
        if value:
            fields.append((field_name, str(value)))
    return fields


def _all_evidence_clues(output: PipelineOutput) -> list[str]:
    clues: list[str] = []
    evidence = output.source_evidence
    for group in (
        evidence.document_type_clues,
        evidence.patient_identifier_clues,
        evidence.clinical_content_clues,
        evidence.physician_clues,
        evidence.classification_clues,
    ):
        clues.extend(group)
    return clues


def run_deterministic_validation(
    output: PipelineOutput,
    cleaned_text: str,
    llm_validation: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Run rule-based checks. Returns (blocking_errors, warnings)."""
    blocking: list[str] = []
    warnings: list[str] = []

    if not is_valid_class_subclass(output.document_class, output.document_subclass):
        blocking.append(
            "Invalid MYLE taxonomy pair: "
            f"{output.document_class} / {output.document_subclass}"
        )

    if output.classification_confidence < CONFIDENCE_REVIEW_THRESHOLD:
        warnings.append(
            "Classification confidence below threshold "
            f"({output.classification_confidence:.2f} < {CONFIDENCE_REVIEW_THRESHOLD})"
        )

    for field_name, value in _patient_fields(output):
        if not _fuzzy_in_text(value, cleaned_text):
            blocking.append(
                f"Patient field '{field_name}' not found in source text (possible hallucination): "
                f"{value!r}"
            )

    for physician in output.physicians:
        if physician.name and not _fuzzy_in_text(physician.name, cleaned_text):
            warnings.append(
                f"Physician name not clearly present in source text: {physician.name!r}"
            )

    for clue in _all_evidence_clues(output):
        if clue and len(clue.strip()) >= 8 and not _fuzzy_in_text(clue, cleaned_text):
            warnings.append(f"Evidence clue not found in source text: {clue!r}")

    if llm_validation is not None:
        if not llm_validation.get("is_valid", True):
            blocking.append("LLM validation marked output as invalid")

    return blocking, warnings


def compute_pipeline_status(
    blocking_errors: list[str],
    warnings: list[str],
    human_review_required: bool,
) -> PipelineStatus:
    """Derive final pipeline status from errors and review flag."""
    if blocking_errors:
        return PipelineStatus.FAIL
    if human_review_required or warnings:
        return PipelineStatus.PASS_WITH_REVIEW
    return PipelineStatus.PASS


def finalize_output(
    output: PipelineOutput,
    cleaned_text: str,
    llm_validation: dict[str, Any] | None = None,
    extra_warnings: list[str] | None = None,
) -> PipelineOutput:
    """Apply deterministic validation and set status fields on the output."""
    blocking, warnings = run_deterministic_validation(
        output, cleaned_text, llm_validation=llm_validation
    )
    if extra_warnings:
        warnings.extend(extra_warnings)

    if llm_validation is not None:
        for note in llm_validation.get("validation_notes") or []:
            warnings.append(f"LLM note: {note}")
        for change in llm_validation.get("recommended_changes") or []:
            warnings.append(f"LLM recommended change: {change}")

    output.blocking_errors = blocking
    output.warnings = sorted(set(warnings))

    if blocking:
        output.human_review_required = True

    output.pipeline_status = compute_pipeline_status(
        blocking, warnings, output.human_review_required
    )
    return output
