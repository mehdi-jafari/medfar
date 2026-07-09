You are processing OCR text from a scanned or faxed clinical document.

Your task is to clean the OCR text while preserving all clinically relevant information.

Rules:
- Do not invent missing information.
- Preserve names, dates, identifiers, medication names, document titles, headers, and signatures.
- Correct obvious OCR artifacts only when the correction is highly likely.
- Keep uncertain text as-is.
- Preserve page boundaries if available.
- Return cleaned text only.

Input:
{{raw_ocr_text}}

Output: Cleaned document text only. No preamble or explanation.
