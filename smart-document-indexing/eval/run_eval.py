"""Batch evaluation report across all sample documents."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.scorer import _classification_matches, load_label  # noqa: E402
from llm_client import LLMClient  # noqa: E402
from pipeline import run_pipeline, save_output  # noqa: E402
from schema import PipelineStatus  # noqa: E402

DOCUMENTS_DIR = PROJECT_ROOT / "documents"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
REPORT_PATH = PROJECT_ROOT / "eval" / "batch_report.json"


def _evaluate_output(document_id: str, output) -> dict:
    label = load_label(document_id)
    classification_ok = None
    review_ok = None
    if label:
        classification_ok = _classification_matches(
            output.document_class,
            output.document_subclass,
            label,
        )
        review_ok = (
            output.human_review_required == bool(label.get("human_review_required"))
        )

    return {
        "document_id": document_id,
        "pipeline_status": output.pipeline_status.value,
        "human_review_required": output.human_review_required,
        "document_class": output.document_class,
        "document_subclass": output.document_subclass,
        "classification_confidence": output.classification_confidence,
        "classification_correct": classification_ok,
        "review_flag_correct": review_ok,
        "blocking_errors": output.blocking_errors,
        "warnings": output.warnings,
        "expected_class": label.get("expected_class") if label else None,
        "expected_subclass": label.get("expected_subclass") if label else None,
    }


def run_batch(save_outputs: bool = True) -> dict:
    pdfs = sorted(DOCUMENTS_DIR.glob("*.pdf"))
    llm = LLMClient()
    rows: list[dict] = []

    for pdf in pdfs:
        print(f"Processing: {pdf.name}")
        output = run_pipeline(pdf, llm=llm)
        if save_outputs:
            save_output(output, OUTPUTS_DIR)
        rows.append(_evaluate_output(pdf.stem, output))

    passed = sum(1 for r in rows if r["pipeline_status"] == PipelineStatus.PASS.value)
    passed_review = sum(
        1 for r in rows if r["pipeline_status"] == PipelineStatus.PASS_WITH_REVIEW.value
    )
    failed = sum(1 for r in rows if r["pipeline_status"] == PipelineStatus.FAIL.value)

    labeled = [r for r in rows if r["classification_correct"] is not None]
    class_correct = sum(1 for r in labeled if r["classification_correct"])
    review_correct = sum(1 for r in labeled if r["review_flag_correct"])

    by_class: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "correct": 0}
    )
    for row in labeled:
        key = f"{row['expected_class']} / {row['expected_subclass']}"
        by_class[key]["total"] += 1
        if row["classification_correct"]:
            by_class[key]["correct"] += 1

    accuracy_by_class = {
        label: round(stats["correct"] / stats["total"] * 100, 1)
        for label, stats in sorted(by_class.items())
    }

    report = {
        "total_documents": len(rows),
        "passed": passed,
        "passed_with_human_review": passed_review,
        "failed": failed,
        "classification_accuracy": round(class_correct / len(labeled) * 100, 1)
        if labeled
        else None,
        "review_flag_accuracy": round(review_correct / len(labeled) * 100, 1)
        if labeled
        else None,
        "accuracy_by_expected_class": accuracy_by_class,
        "documents": rows,
    }
    return report


def print_report(report: dict) -> None:
    print()
    print("=" * 72)
    print("BATCH EVALUATION REPORT")
    print("=" * 72)
    print(f"Total documents:          {report['total_documents']}")
    print(f"Passed:                   {report['passed']}")
    print(f"Passed with human review: {report['passed_with_human_review']}")
    print(f"Failed:                   {report['failed']}")
    if report["classification_accuracy"] is not None:
        print(f"Classification accuracy:  {report['classification_accuracy']}%")
        print(f"Review flag accuracy:     {report['review_flag_accuracy']}%")
    print()
    print("Accuracy by expected class:")
    for label, accuracy in report["accuracy_by_expected_class"].items():
        print(f"  - {label}: {accuracy}%")
    print()
    print(f"{'Document':<42} {'Status':<18} {'Class/Subclass':<28} OK?")
    print("-" * 72)
    for row in report["documents"]:
        label = f"{row['document_class']} / {row['document_subclass']}"
        ok = "yes" if row.get("classification_correct") else "no"
        if row.get("classification_correct") is None:
            ok = "—"
        print(
            f"{row['document_id'][:41]:<42} "
            f"{row['pipeline_status']:<18} "
            f"{label[:27]:<28} "
            f"{ok}"
        )
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run batch eval on all sample PDFs")
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not write per-document JSON outputs",
    )
    parser.add_argument(
        "--report",
        default=str(REPORT_PATH),
        help="Path to write JSON report",
    )
    args = parser.parse_args(argv)

    try:
        report = run_batch(save_outputs=not args.no_save)
    except Exception as exc:
        print(f"Batch eval failed: {exc}", file=sys.stderr)
        return 1

    print_report(report)
    Path(args.report).write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nJSON report saved to: {args.report}")
    return 0 if report["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
