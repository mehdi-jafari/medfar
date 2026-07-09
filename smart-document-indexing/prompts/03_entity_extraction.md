You are extracting patient and physician identifying information from a clinical document.

Return JSON:
{
  "patient_identifiers": {
    "name": null,
    "date_of_birth": null,
    "health_card_number": null,
    "mrn": null,
    "phone": null,
    "address": null,
    "other": []
  },
  "physicians": [
    {
      "name": "",
      "role": "author | recipient | referring | ordering | reading | mentioned | unknown",
      "confidence": 0.0,
      "evidence": ""
    }
  ],
  "ambiguities": []
}

Rules:
- Extract only information present in the document.
- Do not match the patient to an EMR record.
- If multiple physicians appear, include all and assign roles if possible.
- If patient information is blank, missing, or de-identified, return null and add an ambiguity.
- Do not infer physician identity from clinic name alone.
- NEVER use role labels as physician names. Invalid names include: "Reading Physician", "Referring Physician", "Ordering Physician", "Attending Physician", "Doctor", "Physician".
- If only a role label is present (e.g. "Reading Physician") with no actual person name, omit that physician from the physicians array and add an ambiguity.
- Include evidence for each physician.
- Use role values exactly: author, recipient, referring, ordering, reading, mentioned, unknown.

Input:
{{cleaned_document_text}}
