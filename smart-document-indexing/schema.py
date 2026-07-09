"""Pydantic models and MYLE taxonomy validation."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PhysicianRole(str, Enum):
    AUTHOR = "author"
    RECIPIENT = "recipient"
    REFERRING = "referring"
    ORDERING = "ordering"
    READING = "reading"
    MENTIONED = "mentioned"
    UNKNOWN = "unknown"


MYLE_TAXONOMY: dict[str, list[str]] = {
    "Summary": [
        "Medical Summary",
        "Problems and Diagnoses",
        "Discharge Summary",
        "Record Summary Request",
        "Previous Record",
        "Pharmacy",
        "Other",
    ],
    "Clinical Note": [
        "Family Doctor",
        "Specialist",
        "Nursing",
        "Thematic Clinics",
        "Health Professionals",
        "Occupational Health and Safety",
        "Other",
    ],
    "Consultation Reports": [
        "Family Doctor",
        "Specialist",
        "Nursing",
        "Thematic Clinics",
        "Health Professionals",
        "Occupational Health and Safety",
        "Other",
    ],
    "Results": [
        "Laboratory",
        "Imaging",
        "Endoscopy",
        "Cardiology",
        "Special Tests",
        "Other",
    ],
    "Forms": [
        "Medical Certificate",
        "Medical Evaluation",
        "Consent",
        "RAMQ",
        "CSST",
        "SAAQ",
        "Insurance",
        "Other",
    ],
    "Medication and Prescriptions": [
        "Exceptional Medications Request",
        "Prescription Form",
        "Nonpharmacological Prescription",
        "Prescription",
        "Pharmacological Profile",
        "Other",
    ],
    "Requests": [
        "Laboratory Requests",
        "Imaging Requests",
        "External Requests",
        "Consultation Requests",
        "Hospital Services Requests",
        "Other",
    ],
    "Other": [
        "Therapeutic Intensity",
        "Clinical Tools and Monitoring",
        "Questionnaires",
        "Patient Services",
        "Travel Health",
        "Other",
    ],
    "Scanned Paper Record": [
        "Complete",
        "Clinical Notes",
        "Laboratory Results",
        "Imaging Results",
        "Consultation Reports",
        "Medication and Prescriptions",
        "Requests",
    ],
}

CONFIDENCE_REVIEW_THRESHOLD = 0.6


class PipelineStatus(str, Enum):
    PASS = "pass"
    PASS_WITH_REVIEW = "pass_with_review"
    FAIL = "fail"


def is_valid_class_subclass(document_class: str, document_subclass: str) -> bool:
    """Return True if the class/subclass pair is allowed by MYLE taxonomy."""
    subclasses = MYLE_TAXONOMY.get(document_class)
    return subclasses is not None and document_subclass in subclasses


class PatientIdentifiers(BaseModel):
    name: str | None = None
    date_of_birth: str | None = None
    health_card_number: str | None = None
    mrn: str | None = None
    phone: str | None = None
    address: str | None = None
    other: list[str] = Field(default_factory=list)


class Physician(BaseModel):
    name: str
    role: PhysicianRole = PhysicianRole.UNKNOWN
    confidence: float = 0.0
    evidence: str = ""


class SourceEvidence(BaseModel):
    document_type_clues: list[str] = Field(default_factory=list)
    patient_identifier_clues: list[str] = Field(default_factory=list)
    clinical_content_clues: list[str] = Field(default_factory=list)
    physician_clues: list[str] = Field(default_factory=list)
    classification_clues: list[str] = Field(default_factory=list)


class PipelineOutput(BaseModel):
    document_id: str
    document_class: str
    document_subclass: str
    classification_confidence: float = 0.0
    short_description: str = ""
    patient_identifiers: PatientIdentifiers = Field(default_factory=PatientIdentifiers)
    physicians: list[Physician] = Field(default_factory=list)
    routing_support_text: str = ""
    ambiguities: list[str] = Field(default_factory=list)
    human_review_required: bool = False
    pipeline_status: PipelineStatus = PipelineStatus.PASS_WITH_REVIEW
    blocking_errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)
    source_evidence: SourceEvidence = Field(default_factory=SourceEvidence)


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def evidence_to_source_evidence(evidence: dict[str, Any]) -> SourceEvidence:
    """Map step-2 evidence JSON into normalized source_evidence fields."""
    legacy_clinical = _as_list(evidence.get("clinical_keywords"))
    patient_identifier_clues = _as_list(evidence.get("patient_identifier_clues"))
    if not patient_identifier_clues:
        patient_identifier_clues = _as_list(evidence.get("patient_clues"))

    clinical_content_clues = _as_list(evidence.get("clinical_content_clues"))
    if not clinical_content_clues:
        clinical_content_clues = legacy_clinical

    document_type_clues = _as_list(evidence.get("document_type_clues"))
    if not document_type_clues:
        document_type_clues = (
            _as_list(evidence.get("document_titles"))
            + _as_list(evidence.get("form_or_report_clues"))
            + _as_list(evidence.get("document_purpose_clues"))
        )

    physician_clues = _as_list(evidence.get("physician_clues"))
    if not physician_clues:
        physician_clues = _as_list(evidence.get("organization_names"))

    return SourceEvidence(
        document_type_clues=document_type_clues,
        patient_identifier_clues=patient_identifier_clues,
        clinical_content_clues=clinical_content_clues,
        physician_clues=physician_clues,
        classification_clues=(
            _as_list(evidence.get("result_clues"))
            + _as_list(evidence.get("request_clues"))
            + _as_list(evidence.get("medication_clues"))
            + _as_list(evidence.get("appointment_or_administrative_clues"))
        ),
    )
