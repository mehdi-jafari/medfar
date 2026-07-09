You are validating the structured output of a clinical document indexing pipeline.

Check whether:
1. The class/subclass is allowed by the MYLE taxonomy.
2. The classification is supported by evidence in the document.
3. Patient identifiers were extracted only when present.
4. Physicians were extracted only when present.
5. The description is accurate and not hallucinated.
6. Ambiguities and missing information are clearly flagged.
7. human_review_required is true when confidence is low or key information is ambiguous.

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
