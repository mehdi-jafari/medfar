# Design Document — Smart Document Indexing

**Author:** Mehdi Jafari  
**Project:** MEDFAR take-home — MYLE document indexing prototype  
**Repository:** `smart-document-indexing/`

---

## 1. Submission deliverables

| Source | Requirement |
|--------|-------------|
| **Cursor Build Prompt** | Python prototype, 5 prompts, pipeline, structured JSON, **README** with design rationale |
| **#0 Instructions PDF** | Could not extract text (image-only PDF). **Confirm with recruiter** if a separate written PDF is required beyond README + this document. |

**What we submit:**

1. GitHub repository with runnable code  
2. `README.md` — setup, architecture, limitations  
3. **`DESIGN.md` (this file)** — reasoning, rubrics, failure modes  
4. `examples/` — sample outputs (no API key needed to inspect)  
5. `eval/batch_report.json` — measurable results on all 6 PDFs  

---

## 2. Architecture

```
PDF → extract_text() → Step 1 OCR cleanup → Step 2 Evidence
                              ↓                    ↓
                         Step 3 Entities ──→ Step 4 Classification
                                                    ↓
                                              merge() + Step 5 LLM review
                                                    ↓
                                    validators.finalize_output() → JSON
```

**Orchestration:** `pipeline.py` runs steps sequentially. Prompts do not call each other.

**Two-layer validation:**

| Layer | Where | Role |
|-------|-------|------|
| **Deterministic** | `validators.py` | Taxonomy check, confidence threshold, hallucination detection, placeholder physicians → `blocking_errors`, `warnings`, `pipeline_status` |
| **LLM supplementary** | `05_validation.md` | Qualitative notes only; `is_valid: false` becomes a blocking error |

**Status semantics:**

- `pass` — no blockers, no review needed  
- `pass_with_review` — usable with human check  
- `fail` — blocking errors (e.g. hallucinated patient name, LLM invalid)  

---

## 3. Why prompt chaining?

A single mega-prompt tends to:

- Hallucinate patient identifiers while classifying  
- Conflate document purpose with keywords (“referral” → Consultation Request)  
- Skip explicit ambiguity handling  

**Design choice:** separate concerns per step.

| Step | Isolated responsibility |
|------|-------------------------|
| 1 OCR cleanup | Fix noise without inventing facts |
| 2 Evidence | Clues only — no classification |
| 3 Entities | Patient + physicians — no EMR matching |
| 4 Classification | MYLE mapping using evidence + text |
| 5 Validation | Supplementary qualitative review |

Evidence before classification grounds taxonomy decisions. Entity extraction is isolated so identifiers are not invented during classification.

---

## 4. Evaluation rubrics (KPIs)

Implemented in `eval/scorer.py` and `eval/run_eval.py`.

| Step | KPI | How measured |
|------|-----|--------------|
| 0 Extract | Char count, pages | Local only |
| 1 OCR | Key field preservation, length delta | Gold `key_fields_raw` |
| 2 Evidence | Evidence recall | `evidence_must_include` vs output |
| 3 Entities | Patient field accuracy, physician recall | Gold labels |
| 4 Classification | Class/subclass match (+ acceptable alternatives) | Gold labels |
| 5 Validation | Review flag match, self-check | Gold `human_review_required` |
| End-to-end | `pipeline_status`, classification accuracy | Batch report |

**Batch command:** `python eval/run_eval.py`  
**Interactive:** `streamlit run eval/app.py`

---

## 5. Submission results (batch run)

Run date: 2026-07-09 · Model: `gpt-4o` · Documents: 6

| Document | Status | Predicted class | Gold match | Review flag OK |
|----------|--------|-----------------|------------|--------------|
| Appointment notice | pass_with_review | Other / Patient Services | Yes | No (over-flagged) |
| Consultation report | pass_with_review | Clinical Note / Specialist | Yes | No (over-flagged) |
| Imaging | pass_with_review | Results / Imaging | Yes | Yes |
| Prescription | pass_with_review | Requests / Other | **No** | Yes |
| Referral declined | **fail** | Requests / Consultation Requests | **No** | Yes |
| Lab result | pass_with_review | Other / Other | **No** | No |

**Summary:** 3/6 classification correct (50%) · 3/6 review-flag correct (50%) · 0 pass · 5 pass_with_review · 1 fail

### Known failure modes

1. **Prescription (image-only PDF)** — Vision OCR + “reauthorization” wording → `Requests` instead of `Medication and Prescriptions / Prescription Form`.  
2. **Lab result (scanned form)** — Low text yield; repetitive patient header without clear result body → low confidence, `Other / Other`.  
3. **Referral declined (mixed)** — Correctly flagged for review; **fail** due to hallucinated patient name not in source text. Page-level split not implemented.  
4. **Appointment / consultation** — Classification correct but **over-flagged** for review (mixed-page heuristic + LLM notes).  

### What works well

- Imaging ultrasound → `Results / Imaging` (0.90 confidence)  
- Appointment notice → `Other / Patient Services` (after taxonomy prompt tuning)  
- Consultation report → `Clinical Note / Specialist`  
- Placeholder physician names rejected (`Reading Physician` → ambiguity, not fake name)  
- Deterministic validation catches hallucinations on referral declined  

---

## 6. LLM choice

**Default:** OpenAI `gpt-4o` (configurable via `OPENAI_MODEL`).

**Rationale:** Scanned faxes, mixed French/English, image-only prescription PDFs need strong document understanding. Vision fallback used when pymupdf/Tesseract yield is low.

**Alternatives:** Same prompt templates could plug into Gemini or Claude via a swapped `llm_client.py` — not benchmarked in this prototype.

**Cost:** ~5 LLM calls per document (+ vision for image PDFs). Acknowledged limitation.

---

## 7. Taxonomy note

MYLE `Summary` subclass corrected to **`Record Summary Request`** (single term; assignment PDF line-wrap had split it across lines). Removed standalone `Request` under `Summary` to avoid collision with the `Requests` class.

---

## 8. Conscious tradeoffs (what we discarded)

| Discarded | Why |
|-----------|-----|
| EMR patient matching | Out of scope |
| Page-level split indexing | Prototype flags mixed docs for review; segments planned in ROADMAP |
| Production OCR | pymupdf + optional Tesseract + GPT-4o vision fallback |
| REST API / web UI | CLI + Streamlit eval only |
| Fine-tuned classifiers | Prompt-based approach for take-home |

---

## 9. Limitations

- 6 sample documents only — not a golden benchmark  
- 5 LLM calls per doc — latency and cost  
- English/French mixed — no dedicated bilingual prompts  
- Single class/subclass per PDF  
- LLM validation can over-warn; deterministic layer is the trust anchor  
- Tesseract not installed in test environment — prescription uses vision OCR  

---

## 10. Roadmap (next steps)

See **[ROADMAP.md](ROADMAP.md)** for detail. Priority order:

1. **Eval as quality gate** — regression thresholds on batch report  
2. **Prompt tuning** — prescription, lab, mixed referral from failure catalog  
3. **Page-level segmentation** — per-page classification for mixed PDFs  
4. **Production hardening** — OCR benchmark, cost controls, API integration  

---

## 11. How to reproduce

```bash
cd smart-document-indexing
copy .env.example .env   # add OPENAI_API_KEY
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python main.py --all
.\.venv\Scripts\python eval/run_eval.py
```

Example outputs without API: `examples/`
