"""Streamlit eval dashboard — step-by-step wizard in the browser."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.runner import (  # noqa: E402
    STEP_FLOW,
    InteractivePipelineState,
    get_step_info,
    new_state,
    preview_prompt,
    run_step,
)
from eval.scorer import (  # noqa: E402
    load_label,
    score_interactive_step,
    score_pipeline_run,
    summary_score,
)
from llm_client import LLMClient  # noqa: E402

DOCUMENTS_DIR = PROJECT_ROOT / "documents"


def _list_pdfs() -> list[Path]:
    return sorted(DOCUMENTS_DIR.glob("*.pdf"))


def _kpi_icon(passed: bool | None) -> str:
    if passed is True:
        return "✅"
    if passed is False:
        return "❌"
    return "ℹ️"


def _init_session() -> None:
    if "llm" not in st.session_state:
        st.session_state.llm = LLMClient()
    if "pipeline" not in st.session_state:
        st.session_state.pipeline = None
    if "active_doc" not in st.session_state:
        st.session_state.active_doc = None
    if "view_step" not in st.session_state:
        st.session_state.view_step = 0


def _reset_pipeline(pdf_path: Path) -> None:
    st.session_state.pipeline = new_state(pdf_path)
    st.session_state.active_doc = pdf_path.stem
    st.session_state.view_step = 0
    st.session_state.llm = LLMClient()


def _render_progress(state: InteractivePipelineState) -> None:
    cols = st.columns(len(STEP_FLOW))
    for col, step in zip(cols, STEP_FLOW):
        num = step["number"]
        if num <= state.completed_through:
            icon = "✅"
        elif num == state.next_step_number:
            icon = "▶️"
        else:
            icon = "⬜"
        col.markdown(f"{icon} **{num}**  \n{step['title']}")


def _render_kpis(step_score) -> None:
    if not step_score or not step_score.kpis:
        return
    cols = st.columns(min(len(step_score.kpis), 4))
    for index, kpi in enumerate(step_score.kpis):
        with cols[index % len(cols)]:
            st.metric(
                label=f"{_kpi_icon(kpi.passed)} {kpi.name}",
                value=kpi.value,
            )
            if kpi.detail:
                st.caption(kpi.detail)
    if step_score.overall_passed is not None:
        status = "PASS" if step_score.overall_passed else "NEEDS REVIEW"
        st.success(f"Step result: **{status}**")


def _render_step_output(state: InteractivePipelineState, step_number: int) -> None:
    if step_number == 0:
        if state.raw_text:
            st.text_area(
                "Extracted raw text",
                value=state.raw_text,
                height=400,
                disabled=True,
                label_visibility="collapsed",
            )
        return

    step = next((s for s in state.steps if s.step_number == step_number), None)
    if not step:
        return

    if isinstance(step.output, dict):
        st.json(step.output)
    else:
        st.text_area(
            "Model output",
            value=str(step.output),
            height=400,
            disabled=True,
            label_visibility="collapsed",
        )


def _render_step_detail(
    state: InteractivePipelineState,
    step_number: int,
    llm: LLMClient,
    *,
    is_active: bool,
) -> None:
    info = get_step_info(step_number)
    st.subheader(f"Step {step_number}: {info['title']}")

    if step_number <= state.completed_through:
        step_score = score_interactive_step(state, step_number)
        _render_kpis(step_score)
        st.markdown("**Output**")
        _render_step_output(state, step_number)

        if step_number > 0:
            step = next(s for s in state.steps if s.step_number == step_number)
            with st.expander("Filled prompt sent to the model"):
                st.code(step.filled_prompt, language="markdown")
        return

    if not is_active:
        st.info("Complete earlier steps to unlock this one.")
        return

    st.markdown("**Prompt preview**")
    st.code(preview_prompt(state, step_number, llm), language="markdown")

    if step_number == 0:
        st.caption("Local extraction only — no OpenAI API call.")
    else:
        st.caption("Review the prompt above, then run this step.")

    col1, col2 = st.columns([1, 3])
    with col1:
        label = "Extract PDF text" if step_number == 0 else f"Run step {step_number}"
        if st.button(label, type="primary", key=f"run_step_{step_number}"):
            with st.spinner(f"Running step {step_number}…"):
                try:
                    run_step(state, step_number, llm)
                    st.session_state.view_step = step_number
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def main() -> None:
    st.set_page_config(
        page_title="Smart Document Indexing — Eval",
        page_icon="📄",
        layout="wide",
    )
    _init_session()

    st.title("Smart Document Indexing — Eval Dashboard")
    st.caption("Walk through each step in the browser. Results appear here after every step.")

    pdfs = _list_pdfs()
    if not pdfs:
        st.error(f"No PDF files found in `{DOCUMENTS_DIR}`.")
        return

    pdf_options = {pdf.stem: pdf for pdf in pdfs}
    sidebar = st.sidebar
    sidebar.header("Document")
    selected_name = sidebar.selectbox(
        "Choose PDF",
        list(pdf_options.keys()),
        label_visibility="collapsed",
    )
    selected_pdf = pdf_options[selected_name]

    if st.session_state.active_doc != selected_name:
        _reset_pipeline(selected_pdf)

    label = load_label(selected_name)
    if label:
        sidebar.success(
            f"Expected: {label.get('expected_class')} / {label.get('expected_subclass')}"
        )

    state: InteractivePipelineState | None = st.session_state.pipeline
    llm: LLMClient = st.session_state.llm

    sidebar.divider()
    sidebar.header("Actions")
    if sidebar.button("Reset pipeline", use_container_width=True):
        _reset_pipeline(selected_pdf)
        st.rerun()

    if state and not state.is_complete:
        if sidebar.button("Run all remaining steps", use_container_width=True):
            progress = sidebar.progress(0.0)
            status = sidebar.empty()
            try:
                while not state.is_complete:
                    next_step = state.next_step_number
                    info = get_step_info(next_step)
                    status.info(f"Running step {next_step}: {info['title']}…")
                    run_step(state, next_step, llm)
                    progress.progress((next_step + 1) / len(STEP_FLOW))
                st.session_state.view_step = 5
                status.success("Pipeline complete.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    if state:
        sidebar.metric("Tokens used", state.total_tokens)
        sidebar.metric("LLM latency", f"{state.total_latency_s:.1f}s")

    if state is None:
        st.info("Select a document to begin.")
        return

    st.divider()
    _render_progress(state)

    st.divider()
    view_options = list(range(state.completed_through + 1))
    if not state.is_complete:
        view_options.append(state.next_step_number)

    if view_options:
        default_view = state.next_step_number if not state.is_complete else state.completed_through
        if st.session_state.view_step in view_options:
            default_view = st.session_state.view_step
        view_step = st.radio(
            "View step",
            view_options,
            format_func=lambda n: f"Step {n}: {get_step_info(n)['title']}"
            + (" (current)" if n == state.next_step_number and not state.is_complete else "")
            + (" ✓" if n <= state.completed_through else ""),
            horizontal=True,
            index=view_options.index(default_view),
            key="view_step_radio",
        )
        st.session_state.view_step = view_step
    else:
        view_step = 0
        st.session_state.view_step = 0

    is_active = view_step == state.next_step_number and not state.is_complete
    _render_step_detail(state, view_step, llm, is_active=is_active)

    if state.is_complete:
        st.divider()
        st.header("Summary")
        step_scores = score_pipeline_run(state.to_run_result())
        summary_kpis = summary_score(step_scores, state.to_run_result())
        cols = st.columns(min(len(summary_kpis), 4))
        for index, kpi in enumerate(summary_kpis):
            with cols[index % len(cols)]:
                st.metric(
                    label=f"{_kpi_icon(kpi.passed)} {kpi.name}",
                    value=kpi.value,
                )

        rows = []
        for score in step_scores:
            status = "—"
            if score.overall_passed is True:
                status = "PASS"
            elif score.overall_passed is False:
                status = "REVIEW"
            rows.append({"Step": score.step_number, "Name": score.title, "Result": status})
        st.dataframe(rows, use_container_width=True, hide_index=True)

        if state.final_output is not None:
            st.subheader("Final pipeline output")
            st.json(json.loads(state.final_output.model_dump_json()))


if __name__ == "__main__":
    main()
