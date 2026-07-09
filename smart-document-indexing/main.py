"""CLI entrypoint for Smart Document Indexing."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from llm_client import LLMClient
from pipeline import run_pipeline, save_output

PROJECT_ROOT = Path(__file__).parent
DOCUMENTS_DIR = PROJECT_ROOT / "documents"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _collect_pdf_paths(args: argparse.Namespace) -> list[Path]:
    if args.all:
        return sorted(DOCUMENTS_DIR.glob("*.pdf"))
    if args.file:
        path = Path(args.file)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return [path]
    raise ValueError("Provide a file path or use --all")


def _print_summary(results: list[tuple[Path, object, int]]) -> None:
    print("\nSummary")
    print("-" * 100)
    print(
        f"{'Document':<40} {'Status':<18} {'Class/Subclass':<26} {'Conf':>5}  Review"
    )
    print("-" * 100)
    for path, output, _tokens in results:
        label = f"{output.document_class} / {output.document_subclass}"
        review = "YES" if output.human_review_required else "no"
        status = getattr(output.pipeline_status, "value", str(output.pipeline_status))
        print(
            f"{path.name[:39]:<40} {status:<18} {label[:25]:<26} "
            f"{output.classification_confidence:>5.2f}  {review}"
        )
    print("-" * 100)
    total_tokens = sum(tokens for _, _, tokens in results)
    print(f"Total model tokens used: {total_tokens}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MEDFAR Smart Document Indexing prototype"
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to a PDF document to process",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all PDFs in the documents/ folder",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    if not args.all and not args.file:
        parser.error("Provide a file path or use --all")

    try:
        pdf_paths = _collect_pdf_paths(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not pdf_paths:
        print("No PDF files found.", file=sys.stderr)
        return 1

    llm = LLMClient()
    results: list[tuple[Path, object, int]] = []

    for pdf_path in pdf_paths:
        print(f"\nProcessing: {pdf_path.name}")
        try:
            start_tokens = llm.total_tokens
            output = run_pipeline(pdf_path, llm=llm)
            out_path = save_output(output, OUTPUTS_DIR)
            tokens_used = llm.total_tokens - start_tokens
            results.append((pdf_path, output, tokens_used))
            print(f"  -> Saved: {out_path}")
        except Exception as exc:
            logging.exception("Failed to process %s", pdf_path.name)
            print(f"  -> FAILED: {exc}", file=sys.stderr)
            return 1

    _print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
