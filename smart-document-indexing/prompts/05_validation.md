You are performing a supplementary LLM review of a clinical document indexing pipeline output.

Deterministic checks (taxonomy validity, confidence threshold, hallucination checks) are already applied in Python. Your job is to add qualitative review notes only.

Check whether:
1. The classification matches the document purpose (not just keywords).
2. The short_description and routing_support_text are accurate and not hallucinated.
3. Ambiguities and missing information are reasonably flagged.
4. Any remaining classification risk warrants human review.

Input document text:
{{cleaned_document_text}}

Pipeline output:
{{pipeline_output_json}}

Return JSON:
{
  "is_valid": true,
  "validation_notes": [],
  "recommended_changes": [],
  "human_review_required": false
}

Rules:
- Set is_valid to false only for serious issues (wrong document type, unsupported classification, likely hallucinated content).
- Do not repeat deterministic checks already visible in blocking_errors or warnings.
- Keep validation_notes concise and actionable.
