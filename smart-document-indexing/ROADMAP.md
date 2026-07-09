# Roadmap — Smart Document Indexing

**Current state:** Promising prototype with a working 5-step pipeline, deterministic validation, eval dashboard, and batch reporting on 6 sample PDFs.

**Goal:** Move from demo-quality to production-trustworthy indexing — measurable accuracy, fewer silent failures, and coverage across document types and OCR quality tiers.

---

## Step 1 — Make evaluation a quality gate (not a demo)

**Why:** The architecture is sound, but trust comes from measurable regression control. One dashboard result or one good example is not enough.

**What to do:**

- Run `eval/run_eval.py` on every prompt or pipeline change; treat it like a test suite.
- Expand `eval/labels/` beyond class/subclass:
  - Required patient fields per document
  - Expected `human_review_required`
  - Forbidden physician placeholders
  - Minimum evidence clues per category
- Add pass thresholds to the batch report, e.g.:
  - Classification accuracy ≥ 85% on labeled samples
  - Review-flag accuracy = 100% on mixed/ambiguous docs
  - Zero tolerated `fail` on clear single-type documents (lab, imaging, prescription)
- Store `eval/batch_report.json` history and diff across runs to catch regressions when prompts change.

**Done when:** A prompt edit that breaks appointment-notice classification or referral-declined review flag is caught automatically before merge.

---

## Step 2 — Close the loop: tune prompts from measured failures

**Why:** Validation is stricter now, but classification and entity errors still need targeted prompt fixes — not more narrative validation.

**What to do:**

- Use `eval/batch_report.json` + per-step UI review to maintain a **failure catalog** (e.g. “appointment notice → Consultation Requests”, “imaging → Reading Physician as name”).
- Iterate prompts in priority order:
  1. `04_taxonomy_classification.md` — document-purpose rules per MYLE branch (admin vs request vs result)
  2. `03_entity_extraction.md` — named physicians only; role labels → ambiguity
  3. `02_evidence_extraction.md` — keep identity vs clinical content separated
- A/B test prompt versions: `prompts/v2/...` vs current, compare batch metrics side-by-side.
- When LLM validation disagrees with deterministic checks, prefer **blocking_errors** for hard failures; keep LLM notes supplementary.

**Done when:** All 6 sample documents reach `pass` or justified `pass_with_review`, with no taxonomy mismatches on gold labels.

---

## Step 3 — Handle multi-document and page-level PDFs

**Why:** Real fax batches often contain multiple document types in one file (e.g. referral declined + medication form). Single class/subclass + a review flag is not enough for routing.

**What to do:**

- Add a **page segmentation** step (before or after evidence extraction):
  - Detect page boundaries and topic shifts
  - Produce one evidence + classification block per segment
- Output schema extension:
  ```json
  {
    "segments": [
      { "pages": [1], "document_class": "...", "document_subclass": "..." },
      { "pages": [2], "document_class": "...", "document_subclass": "..." }
    ],
    "human_review_required": true
  }
  ```
- Add gold labels for page-level expectations on `referral declined` and any future mixed samples.
- Route each segment independently; flag the parent PDF when segments disagree or confidence is low.

**Done when:** Mixed PDFs get per-page (or per-segment) classifications instead of one forced best-fit label.

---

## Step 4 — Production hardening: OCR, cost, and integration

**Why:** Five LLM calls per document and vision fallback for image PDFs do not scale to high-volume clinic fax intake without controls.

**What to do:**

| Area | Action |
|------|--------|
| **OCR** | Benchmark pymupdf vs Tesseract vs vision per document type; cache raw text; only call vision when character yield is below threshold |
| **Cost / latency** | Log tokens per step; explore cheaper model for steps 1–2; keep stronger model for classification + validation |
| **Integration** | Thin REST or queue worker: `POST /index` → PDF in, JSON out; persist `pipeline_status` for downstream routing |
| **Bilingual** | Explicit French/English handling in OCR cleanup and evidence prompts (RAMQ, CSST, bilingual lab headers) |
| **Benchmark scale** | Grow from 6 → 50 → 200 labeled documents across MYLE classes and OCR quality tiers |

**Done when:** Pipeline runs in batch on a folder with predictable cost per doc, stable OCR on scanned labs and image-only prescriptions, and a clear integration contract for MYLE.

---

## Suggested order

```
Step 1 (eval gate)  →  Step 2 (prompt tuning)  →  Step 3 (page split)  →  Step 4 (scale & integrate)
         ↑_____________________|  (continuous)
```

Steps 1 and 2 can run in parallel with small samples. Step 3 depends on accurate per-page evidence (Step 2). Step 4 is the path to production deployment.

---

## Out of scope (unchanged)

- EMR patient matching
- Fine-tuned classifiers (unless eval proves prompts plateau)
- Full production OCR vendor integration (unless Step 4 benchmarking requires it)

---

## Quick reference — commands

```bash
# Batch quality report (all sample PDFs)
.\.venv\Scripts\python eval/run_eval.py

# Interactive step-by-step review
.\.venv\Scripts\streamlit run eval/app.py

# Process all documents
.\.venv\Scripts\python main.py --all
```
