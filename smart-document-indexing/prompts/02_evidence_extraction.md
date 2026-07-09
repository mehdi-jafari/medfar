You are analyzing a clinical document.

Extract only evidence explicitly present in the document.
Do not classify the document yet.

Return JSON with:
{
  "document_titles": [],
  "organization_names": [],
  "dates": [],
  "clinical_keywords": [],
  "document_purpose_clues": [],
  "form_or_report_clues": [],
  "medication_clues": [],
  "result_clues": [],
  "request_clues": [],
  "appointment_or_administrative_clues": [],
  "uncertain_or_low_quality_text": []
}

Rules:
- Only extract what is present.
- Do not infer.
- If text is unclear, include it in uncertain_or_low_quality_text.
- Keep evidence short and useful for classification.
- If the document appears to contain multiple document types across pages, note page-specific clues in document_purpose_clues.

Input:
{{cleaned_document_text}}
