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
    MENTIONED = "mentioned"
    UNKNOWN = "unknown"


MYLE_TAXONOMY: dict[str, list[str]] = {
    "Summary": [
        "Medical Summary",
        "Problems and Diagnoses",
        "Discharge Summary",
        "Record Summary",
        "Request",
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
    patient_clues: list[str] = Field(default_factory=list)
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
    validation_notes: list[str] = Field(default_factory=list)
    source_evidence: SourceEvidence = Field(default_factory=SourceEvidence)


def evidence_to_source_evidence(evidence: dict[str, Any]) -> SourceEvidence:
    """Map step-2 evidence JSON into source_evidence fields."""
    return SourceEvidence(
        document_type_clues=(
            evidence.get("document_titles", [])
            + evidence.get("form_or_report_clues", [])
            + evidence.get("document_purpose_clues", [])
        ),
        patient_clues=evidence.get("clinical_keywords", []),
        physician_clues=evidence.get("organization_names", []),
        classification_clues=(
            evidence.get("result_clues", [])
            + evidence.get("request_clues", [])
            + evidence.get("medication_clues", [])
            + evidence.get("appointment_or_administrative_clues", [])
        ),
    )
