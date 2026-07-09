You are analyzing a clinical document.

Extract only evidence explicitly present in the document.
Do not classify the document yet.

Return JSON with:
{
  "document_type_clues": [],
  "patient_identifier_clues": [],
  "clinical_content_clues": [],
  "physician_clues": [],
  "dates": [],
  "medication_clues": [],
  "result_clues": [],
  "request_clues": [],
  "appointment_or_administrative_clues": [],
  "uncertain_or_low_quality_text": []
}

Category rules:
- document_type_clues: titles, headers, form labels, report types (e.g. "CT report", "appointment notice")
- patient_identifier_clues: name fragments, DOB, health card, MRN, phone, address — identity only
- clinical_content_clues: diagnoses, symptoms, findings, lab values, imaging impressions — medical content, NOT patient identity
- physician_clues: named physicians, signer lines, clinic/doctor names used as physician evidence
- Do NOT put clinical findings in patient_identifier_clues
- Do NOT put patient identifiers in clinical_content_clues

Rules:
- Only extract what is present.
- Do not infer.
- If text is unclear, include it in uncertain_or_low_quality_text.
- Keep evidence short and useful for classification.
- If the document appears to contain multiple document types across pages, note page-specific clues in document_type_clues.

Input:
{{cleaned_document_text}}
