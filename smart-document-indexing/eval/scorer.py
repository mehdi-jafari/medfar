"""KPI scoring for pipeline steps against gold labels."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from schema import is_valid_class_subclass

LABELS_DIR = Path(__file__).parent / "labels"


@dataclass
class KPI:
    name: str
    value: str
    passed: bool | None = None
    detail: str = ""


@dataclass
class StepScore:
    step_number: int
    title: str
    kpis: list[KPI] = field(default_factory=list)
    overall_passed: bool | None = None


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _fuzzy_in_text(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    return _normalize_text(needle) in _normalize_text(haystack)


def _collect_evidence_strings(evidence: dict[str, Any]) -> str:
    parts: list[str] = []
    for value in evidence.values():
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value:
            parts.append(str(value))
    return " ".join(parts)


def load_label(document_id: str) -> dict[str, Any] | None:
    """Load gold label JSON for a document id."""
    path = LABELS_DIR / f"{document_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_labels() -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    for path in sorted(LABELS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        labels.append(data)
    return labels


def _classification_matches(
    predicted_class: str,
    predicted_subclass: str,
    label: dict[str, Any],
) -> bool:
    if (
        predicted_class == label.get("expected_class")
        and predicted_subclass == label.get("expected_subclass")
    ):
        return True

    for alt in label.get("acceptable_classifications") or []:
        if (
            predicted_class == alt.get("document_class")
            and predicted_subclass == alt.get("document_subclass")
        ):
            return True
    return False


def score_step1(
    raw_text: str, cleaned_text: str, label: dict[str, Any] | None, step_meta: dict[str, Any]
) -> StepScore:
    kpis: list[KPI] = []

    key_fields = (label or {}).get("key_fields_raw") or []
    preserved = 0
    for field_value in key_fields:
        if _fuzzy_in_text(field_value, cleaned_text):
            preserved += 1
    if key_fields:
        passed = preserved == len(key_fields)
        kpis.append(
            KPI(
                name="Key field preservation",
                value=f"{preserved}/{len(key_fields)}",
                passed=passed,
                detail="Critical identifiers still present after cleanup",
            )
        )

    raw_len = len(raw_text)
    cleaned_len = len(cleaned_text)
    delta_pct = abs(cleaned_len - raw_len) / max(raw_len, 1) * 100
    kpis.append(
        KPI(
            name="Length delta",
            value=f"{delta_pct:.1f}%",
            passed=delta_pct <= 15,
            detail=f"{raw_len} → {cleaned_len} chars",
        )
    )
    kpis.append(KPI(name="Tokens", value=str(step_meta.get("tokens_used", "—"))))
    kpis.append(
        KPI(
            name="Latency",
            value=f"{step_meta.get('latency_s', 0):.2f}s",
        )
    )

    scored = [kpi for kpi in kpis if kpi.passed is not None]
    overall = all(kpi.passed for kpi in scored) if scored else None
    return StepScore(step_number=1, title="OCR Cleanup", kpis=kpis, overall_passed=overall)


def score_step2(
    evidence: dict[str, Any], label: dict[str, Any] | None, step_meta: dict[str, Any]
) -> StepScore:
    kpis: list[KPI] = []
    must_include = (label or {}).get("evidence_must_include") or []
    evidence_blob = _collect_evidence_strings(evidence)
    found = sum(1 for clue in must_include if _fuzzy_in_text(clue, evidence_blob))

    if must_include:
        kpis.append(
            KPI(
                name="Evidence recall",
                value=f"{found}/{len(must_include)}",
                passed=found >= max(1, len(must_include) - 1),
                detail=", ".join(must_include),
            )
        )

    uncertain = evidence.get("uncertain_or_low_quality_text") or []
    kpis.append(
        KPI(
            name="Uncertainty flags",
            value=str(len(uncertain)),
            detail="Low-quality text segments noted",
        )
    )
    kpis.append(KPI(name="Tokens", value=str(step_meta.get("tokens_used", "—"))))
    kpis.append(
        KPI(
            name="Latency",
            value=f"{step_meta.get('latency_s', 0):.2f}s",
        )
    )

    scored = [kpi for kpi in kpis if kpi.passed is not None]
    overall = all(kpi.passed for kpi in scored) if scored else None
    return StepScore(
        step_number=2, title="Evidence Extraction", kpis=kpis, overall_passed=overall
    )


def score_step3(
    entities: dict[str, Any], label: dict[str, Any] | None, step_meta: dict[str, Any]
) -> StepScore:
    kpis: list[KPI] = []
    predicted = entities.get("patient_identifiers") or {}
    gold = (label or {}).get("patient_identifiers") or {}

    matched = 0
    checked = 0
    for field_name, expected in gold.items():
        if expected is None:
            continue
        checked += 1
        actual = predicted.get(field_name)
        if actual and _fuzzy_in_text(str(expected), str(actual)):
            matched += 1
    if checked:
        kpis.append(
            KPI(
                name="Patient field accuracy",
                value=f"{matched}/{checked}",
                passed=matched == checked,
            )
        )

    gold_physicians = (label or {}).get("physicians") or []
    predicted_physicians = entities.get("physicians") or []
    physician_blob = " ".join(
        f"{p.get('name', '')} {p.get('role', '')}" for p in predicted_physicians
    )
    phys_found = 0
    for gold_phys in gold_physicians:
        name_part = gold_phys.get("name_substring") or gold_phys.get("name") or ""
        if _fuzzy_in_text(name_part, physician_blob):
            phys_found += 1
    if gold_physicians:
        kpis.append(
            KPI(
                name="Physician recall",
                value=f"{phys_found}/{len(gold_physicians)}",
                passed=phys_found == len(gold_physicians),
            )
        )

    kpis.append(
        KPI(
            name="Ambiguity notes",
            value=str(len(entities.get("ambiguities") or [])),
        )
    )
    kpis.append(KPI(name="Tokens", value=str(step_meta.get("tokens_used", "—"))))
    kpis.append(
        KPI(
            name="Latency",
            value=f"{step_meta.get('latency_s', 0):.2f}s",
        )
    )

    scored = [kpi for kpi in kpis if kpi.passed is not None]
    overall = all(kpi.passed for kpi in scored) if scored else None
    return StepScore(
        step_number=3, title="Entity Extraction", kpis=kpis, overall_passed=overall
    )


def score_step4(
    classification: dict[str, Any],
    label: dict[str, Any] | None,
    step_meta: dict[str, Any],
) -> StepScore:
    kpis: list[KPI] = []
    pred_class = str(classification.get("document_class", ""))
    pred_subclass = str(classification.get("document_subclass", ""))
    confidence = float(classification.get("classification_confidence", 0.0) or 0.0)

    if label:
        class_ok = _classification_matches(pred_class, pred_subclass, label)
        kpis.append(
            KPI(
                name="Classification",
                value=f"{pred_class} / {pred_subclass}",
                passed=class_ok,
                detail=(
                    f"Expected {label.get('expected_class')} / "
                    f"{label.get('expected_subclass')}"
                ),
            )
        )
        expected_review = bool(label.get("human_review_required"))
        pred_review = bool(classification.get("human_review_required"))
        kpis.append(
            KPI(
                name="Review flag (step 4)",
                value="YES" if pred_review else "no",
                passed=pred_review == expected_review,
                detail=f"Expected {'YES' if expected_review else 'no'}",
            )
        )

    kpis.append(
        KPI(
            name="Taxonomy valid",
            value="yes" if is_valid_class_subclass(pred_class, pred_subclass) else "no",
            passed=is_valid_class_subclass(pred_class, pred_subclass),
        )
    )
    kpis.append(
        KPI(
            name="Confidence",
            value=f"{confidence:.2f}",
            passed=confidence >= 0.6 or (label and label.get("human_review_required")),
        )
    )
    kpis.append(KPI(name="Tokens", value=str(step_meta.get("tokens_used", "—"))))
    kpis.append(
        KPI(
            name="Latency",
            value=f"{step_meta.get('latency_s', 0):.2f}s",
        )
    )

    scored = [kpi for kpi in kpis if kpi.passed is not None]
    overall = all(kpi.passed for kpi in scored) if scored else None
    return StepScore(
        step_number=4,
        title="Taxonomy Classification",
        kpis=kpis,
        overall_passed=overall,
    )


def score_step5(
    validation: dict[str, Any],
    final_output: Any,
    label: dict[str, Any] | None,
    step_meta: dict[str, Any],
) -> StepScore:
    kpis: list[KPI] = []
    is_valid = bool(validation.get("is_valid", True))
    kpis.append(
        KPI(
            name="Model self-check",
            value="valid" if is_valid else "invalid",
            passed=is_valid,
        )
    )

    if label and final_output is not None:
        expected_review = bool(label.get("human_review_required"))
        final_review = bool(getattr(final_output, "human_review_required", False))
        kpis.append(
            KPI(
                name="Final review flag",
                value="YES" if final_review else "no",
                passed=final_review == expected_review,
                detail=f"Expected {'YES' if expected_review else 'no'}",
            )
        )

    notes = validation.get("validation_notes") or []
    kpis.append(KPI(name="Validation notes", value=str(len(notes))))
    kpis.append(KPI(name="Tokens", value=str(step_meta.get("tokens_used", "—"))))
    kpis.append(
        KPI(
            name="Latency",
            value=f"{step_meta.get('latency_s', 0):.2f}s",
        )
    )

    scored = [kpi for kpi in kpis if kpi.passed is not None]
    overall = all(kpi.passed for kpi in scored) if scored else None
    return StepScore(
        step_number=5, title="Validation", kpis=kpis, overall_passed=overall
    )


def score_interactive_step(state: Any, step_number: int) -> StepScore | None:
    """Score one step from interactive pipeline state."""
    label = load_label(state.document_id)

    if step_number == 0 and state.raw_text:
        return StepScore(
            step_number=0,
            title="PDF Text Extraction",
            kpis=[
                KPI(name="Characters extracted", value=str(len(state.raw_text))),
                KPI(
                    name="Pages detected",
                    value=str(state.raw_text.count("--- Page")),
                ),
            ],
            overall_passed=None,
        )

    for step in state.steps:
        if step.step_number != step_number:
            continue
        meta = {"tokens_used": step.tokens_used, "latency_s": step.latency_s}
        if step_number == 1:
            return score_step1(
                state.raw_text or "", str(step.output), label, meta
            )
        if step_number == 2:
            return score_step2(step.output, label, meta)
        if step_number == 3:
            return score_step3(step.output, label, meta)
        if step_number == 4:
            return score_step4(step.output, label, meta)
        if step_number == 5:
            return score_step5(
                step.output, state.final_output, label, meta
            )
    return None


def score_pipeline_run(run_result: Any) -> list[StepScore]:
    """Score all steps for a PipelineRunResult."""
    label = load_label(run_result.document_id)
    scores: list[StepScore] = []

    step_outputs: dict[int, Any] = {}
    for step in run_result.steps:
        step_outputs[step.step_number] = step

    if 1 in step_outputs:
        step = step_outputs[1]
        scores.append(
            score_step1(
                run_result.raw_text,
                str(step.output),
                label,
                {"tokens_used": step.tokens_used, "latency_s": step.latency_s},
            )
        )
    if 2 in step_outputs:
        step = step_outputs[2]
        scores.append(
            score_step2(
                step.output,
                label,
                {"tokens_used": step.tokens_used, "latency_s": step.latency_s},
            )
        )
    if 3 in step_outputs:
        step = step_outputs[3]
        scores.append(
            score_step3(
                step.output,
                label,
                {"tokens_used": step.tokens_used, "latency_s": step.latency_s},
            )
        )
    if 4 in step_outputs:
        step = step_outputs[4]
        scores.append(
            score_step4(
                step.output,
                label,
                {"tokens_used": step.tokens_used, "latency_s": step.latency_s},
            )
        )
    if 5 in step_outputs:
        step = step_outputs[5]
        scores.append(
            score_step5(
                step.output,
                run_result.final_output,
                label,
                {"tokens_used": step.tokens_used, "latency_s": step.latency_s},
            )
        )

    return scores


def summary_score(step_scores: list[StepScore], run_result: Any) -> list[KPI]:
    """End-to-end summary KPIs."""
    kpis: list[KPI] = []
    scored = [s for s in step_scores if s.overall_passed is not None]
    if scored:
        passed = sum(1 for s in scored if s.overall_passed)
        kpis.append(
            KPI(
                name="Steps passed",
                value=f"{passed}/{len(scored)}",
                passed=passed == len(scored),
            )
        )

    kpis.append(KPI(name="Total tokens", value=str(run_result.total_tokens)))
    kpis.append(
        KPI(
            name="Total LLM latency",
            value=f"{run_result.total_latency_s:.2f}s",
        )
    )

    if run_result.final_output is not None:
        output = run_result.final_output
        kpis.append(
            KPI(
                name="Final classification",
                value=f"{output.document_class} / {output.document_subclass}",
            )
        )
        kpis.append(
            KPI(
                name="Human review required",
                value="YES" if output.human_review_required else "no",
            )
        )
    return kpis
