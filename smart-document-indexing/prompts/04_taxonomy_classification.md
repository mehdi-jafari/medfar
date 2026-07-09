You are classifying a clinical document into the MYLE document taxonomy.

Use only the allowed class/subclass pairs.

Allowed taxonomy:
{{taxonomy}}

Evidence:
{{evidence_json}}

Cleaned document text:
{{cleaned_document_text}}

Return JSON:
{
  "document_class": "",
  "document_subclass": "",
  "classification_confidence": 0.0,
  "short_description": "",
  "routing_support_text": "",
  "classification_reasoning": "",
  "alternative_classifications": [],
  "human_review_required": false
}

Rules:
- Choose exactly one class and one subclass.
- The subclass must belong to the selected class.
- If uncertain, choose the best match and lower the confidence.
- If the document is administrative but related to care, use the closest taxonomy option.
- If no clean fit exists, use Other / Other and explain why.
- Do not include patient matching.
- routing_support_text should be a concise semantic summary useful for routing rules.
- If multiple document types appear in one PDF (e.g. referral notice plus medication form), set human_review_required to true, lower confidence, and explain in classification_reasoning.
