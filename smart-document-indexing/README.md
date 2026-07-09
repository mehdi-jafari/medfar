# Smart Document Indexing

MEDFAR take-home prototype: a Python pipeline that processes clinical PDF/fax documents and produces structured JSON for MYLE document indexing.

**Repository:** https://github.com/mehdi-jafari/medfar

**Written submission:** [DESIGN.pdf](DESIGN.pdf) (assignment write-up) · [DESIGN.md](DESIGN.md) · **Roadmap:** [ROADMAP.md](ROADMAP.md) · **Examples:** [examples/](examples/)

## Quick start

**Requirements:** Python 3.10+ (stable), OpenAI API key

```bash
cd smart-document-indexing
py -3.10 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
# Edit .env and set OPENAI_API_KEY
```

Run on one document:

```bash
.\.venv\Scripts\python main.py "documents\Doc - appointment notice - blank.pdf"
```

Run on all sample documents:

```bash
.\.venv\Scripts\python main.py --all
```

Outputs are written to `outputs/{document_name}.json`.

### Eval dashboard

Inspect each pipeline step (prompt, model output, KPIs) in a browser UI:

```bash
.\.venv\Scripts\streamlit run eval/app.py
```

Use the sidebar to pick a document, then click through each step in the UI:
1. **Extract PDF text** (local, no API)
2. **Run step 1–5** one at a time — prompt preview, output, and KPIs appear in the browser after each step
3. Or use **Run all remaining steps** in the sidebar to finish in one go

Gold labels live in `eval/labels/`.

Batch evaluation across all sample PDFs:

```bash
.\.venv\Scripts\python eval/run_eval.py
```

## Submission results

Batch eval on all 6 sample PDFs (`gpt-4o`, 2026-07-09). Full report: `eval/batch_report.json`.

| Document | Status | Classification | Gold match |
|----------|--------|----------------|------------|
| Appointment notice | pass_with_review | Other / Patient Services | Yes |
| Consultation report | pass_with_review | Clinical Note / Specialist | Yes |
| Imaging | pass_with_review | Results / Imaging | Yes |
| Prescription | pass_with_review | Requests / Other | No |
| Referral declined | fail | Requests / Consultation Requests | No |
| Lab result | pass_with_review | Other / Other | No |

**Totals:** 0 pass · 5 pass_with_review · 1 fail · **50%** classification accuracy · **50%** review-flag accuracy

Known issues and reasoning: [DESIGN.md §5](DESIGN.md#5-submission-results-batch-run).

### Deliverables

Per the take-home assignment (*#0 Instructions - Take Home Assignment*):

| Requirement | Location |
|-------------|----------|
| **Written document** (PDF / markdown) | **`DESIGN.pdf`** — primary submission |
| Prompts | `prompts/` |
| Output for all sample documents | `outputs/` (run `main.py --all`) |
| Runnable pipeline | [github.com/mehdi-jafari/medfar](https://github.com/mehdi-jafari/medfar) (`smart-document-indexing/`) |
| Setup instructions | `README.md` |
| Sample JSON (no API key) | `examples/` |
| Batch metrics | `eval/batch_report.json` |

### Optional: Tesseract OCR

For image-only PDFs (e.g. prescription form), install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) and add it to your PATH. If Tesseract is unavailable, the pipeline falls back to GPT-4o vision transcription (uses additional API calls).

## Architecture

```mermaid
flowchart TD
    main[main.py] --> pipeline[pipeline.py]
    pipeline --> extract[extract.py]
    extract --> p1[01_ocr_cleanup]
    p1 --> p2[02_evidence_extraction]
    p1 --> p3[03_entity_extraction]
    p2 --> p4[04_taxonomy_classification]
    p3 --> p4
    p4 --> merge[merge_and_validate]
    merge --> p5[05_validation]
    p5 --> output[outputs/doc.json]
```

Prompts do **not** call each other. `pipeline.py` orchestrates the chain and passes each step's output as input to the next.

| Step | Purpose |
|------|---------|
| 1. OCR cleanup | Clean fax/OCR noise while preserving clinical facts |
| 2. Evidence extraction | Extract clues only — no classification yet |
| 3. Entity extraction | Patient identifiers and physicians (no EMR matching) |
| 4. Taxonomy classification | Map to MYLE class/subclass + routing text |
| 5. Validation | Check output against document; flag review |

## Why prompt chaining?

A single mega-prompt tends to hallucinate patient data and misclassify ambiguous documents. Separating steps:

- **Evidence before classification** grounds taxonomy decisions in explicit document clues
- **Entity extraction** is isolated so identifiers are not invented during classification
- **Validation** acts as a final safety check before output is saved

## Output schema

Each document produces JSON with:

- `document_class` / `document_subclass` (MYLE taxonomy)
- `classification_confidence`
- `short_description`
- `patient_identifiers` (name, DOB, health card, etc.)
- `physicians` (name, role, confidence, evidence)
- `routing_support_text` — concise summary for semantic routing rules
- `ambiguities` — unclear or missing information
- `human_review_required` — flag for manual indexing
- `pipeline_status` — `pass`, `pass_with_review`, or `fail`
- `blocking_errors` — deterministic failures (invalid taxonomy, hallucinated fields, LLM invalid)
- `warnings` — non-blocking issues (low confidence, placeholder physicians, evidence mismatches)
- `validation_notes` — supplementary LLM review notes
- `source_evidence` — clues used for classification (`patient_identifier_clues`, `clinical_content_clues`, etc.)

**Taxonomy:** `Summary` includes `Record Summary Request` (single subclass per MYLE spec; not separate `Record Summary` + `Request`).

## How ambiguity is handled

- Entity step returns `null` for missing patient fields and adds entries to `ambiguities`
- Classification step can return `alternative_classifications` and lower confidence
- Acceptable ambiguity (e.g. Clinical Note vs Consultation Reports for a specialist note) is captured with lower confidence rather than forced wrong answers
- Mixed-document PDFs (e.g. referral declined + medication form) are flagged for human review

## When `human_review_required` is true

The flag is set when **any** of these apply:

- Classification confidence &lt; 0.6
- Invalid MYLE class/subclass pair (Python-side taxonomy check)
- Evidence suggests multiple document types in one PDF
- Classification step sets the flag (e.g. mixed pages)
- Validation step recommends review or marks output invalid

## Semantic routing

`routing_support_text` is a short, factual summary designed for routing rules in MYLE — e.g. *"Specialist appointment notice for referred patient, consultation on Apr 29 2026"*. Combined with class/subclass and physician roles, this supports automated routing to the correct clinician inbox without EMR patient matching.

## Sample documents and expected classifications

| Document | Expected class | Expected subclass | Notes |
|----------|---------------|-------------------|-------|
| Résultat - Laboratoire | Results | Laboratory | Scanned; OCR/vision may apply |
| imaging | Results | Imaging | |
| consultation report | Clinical Note or Consultation Reports | Specialist | Either class acceptable |
| prescription | Medication and Prescriptions | Prescription Form | Image-only PDF |
| appointment notice | Other | Patient Services | |
| referral declined | Mixed | Mixed | **Should flag human review** |

## What was discarded

- EMR patient matching (explicitly out of scope)
- Production-grade OCR pipeline
- Web UI / REST API
- Fine-tuned classifiers
- Full benchmark evaluation suite
- Page-level split indexing (noted as future work)

## Limitations

- Prototype only — not production OCR quality
- Evaluated on 6 provided samples, not a golden dataset
- English/French mixed content; no dedicated bilingual handling
- 5 LLM calls per document (cost/latency)
- Image-only PDFs require Tesseract or GPT-4o vision fallback
- Single class/subclass per document (mixed PDFs get one best-fit + review flag)

## Roadmap

See **[ROADMAP.md](ROADMAP.md)** for the prioritized plan to move from prototype to production-ready indexing.

| Phase | Status | Description |
|-------|--------|-------------|
| Core pipeline | Done | 5-step chain, CLI, JSON output |
| Eval labels + batch report | Done | `eval/labels/`, `eval/run_eval.py`, Streamlit dashboard |
| Deterministic validation | Done | `pipeline_status`, `blocking_errors`, `warnings` |
| Prompt tuning from eval | Next | Close taxonomy/entity failure modes on 6 samples |
| Page-level classification | Planned | Split multi-document PDFs per page |
| Production hardening | Planned | OCR benchmark, per-step model routing, cost controls, API integration |
| Per-step model comparison | Planned | Eval-gated API + OSS model selection per pipeline step |
| Benchmark dataset | Planned | 200+ labeled documents across MYLE classes and OCR quality tiers |

## Evaluation

Implemented in `eval/`:

- **Gold labels** — `eval/labels/` (6 sample PDFs)
- **Batch report** — `eval/run_eval.py` → `eval/batch_report.json`
- **Dashboard** — `streamlit run eval/app.py` (per-step prompt, output, KPIs)
- **Scorer** — `eval/scorer.py` (deterministic KPIs per step)

See [DESIGN.md §4](DESIGN.md#4-evaluation-rubrics-kpis) for rubrics.

## Project structure

```
smart-document-indexing/
  documents/          # Sample PDFs
  prompts/            # 01–05 markdown prompt templates
  outputs/            # Generated JSON (gitignored)
  eval/               # Eval dashboard, scorer, gold labels
    app.py            # Streamlit UI
    run_eval.py       # Batch test report
    batch_report.json # Latest batch metrics
    scorer.py         # Per-step KPI calculations
    labels/           # Expected outputs per sample PDF
  examples/           # Sample outputs for reviewers (no API key)
  DESIGN.md           # Design rationale and submission results
  ROADMAP.md          # Next steps
  extract.py          # PDF text extraction
  schema.py           # Pydantic models + MYLE taxonomy
  llm_client.py       # OpenAI client
  pipeline.py         # Pipeline orchestration
  main.py             # CLI entrypoint
  requirements.txt
  .env.example
  README.md
```

## LLM configuration

Default model: `gpt-4o` (configurable via `OPENAI_MODEL` in `.env`).

Gemini and Claude could be evaluated using the same prompt templates and a swapped `llm_client.py` implementation.
