"""
app.py - InsightAgent v2 Streamlit UI (step 8, the last step).

Layout/structure follows the wireframe ONLY:
  - left nav (Ask a question / Schema explorer / Query history)
  - answer card = one-line summary + generated-SQL panel + chart/table toggle
    + self-check display
  - clarification rendered as a bubble with TAPPABLE option buttons
All content is Pagila (rentals, films, customers, payments).

Run:  streamlit run app.py
"""
from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from insightagent.pipeline import answer_question
from insightagent.summary import summarize_answer
from insightagent.table_descriptions import TABLE_DESCRIPTIONS

st.set_page_config(page_title="Analytics Q&A", page_icon="📊", layout="wide")

st.session_state.setdefault("messages", [])   # [{role, content?, result?, summary?}]
st.session_state.setdefault("history", [])     # resolved questions for the resolver


# --- helpers ---------------------------------------------------------------

def _df(columns: list[str], rows: list[tuple]) -> pd.DataFrame:
    clean = [[float(c) if isinstance(c, Decimal) else c for c in row] for row in rows]
    return pd.DataFrame(clean, columns=columns)


def _chart_series(df: pd.DataFrame):
    """A label+value shape that's worth charting, else None."""
    if len(df) < 2 or df.shape[1] < 2:
        return None
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    lab = [c for c in df.columns if c not in num]
    if num and lab:
        return df.set_index(lab[0])[num[0]]
    return None


def render_answer_card(result, summary: str) -> None:
    if summary:
        st.markdown(f"**{summary}**")

    if result.sql:
        with st.expander("🔎 Generated SQL", expanded=False):
            st.code(result.sql, language="sql")

    if result.rows:
        df = _df(result.columns, result.rows)
        series = _chart_series(df)
        tab_chart, tab_table = st.tabs(["📊 Chart", "🗂 Table"])
        with tab_table:
            st.dataframe(df, use_container_width=True, hide_index=True)
        with tab_chart:
            if series is not None:
                st.bar_chart(series)
            elif df.shape == (1, 1):
                st.metric(result.columns[0], str(result.rows[0][0]))
            else:
                st.caption("No chart for this result shape — see the Table tab.")
        if result.truncated:
            st.caption(f"Showing the first {result.row_count} rows (truncated).")

    # self-check display
    if result.source == "catalog":
        st.info("✓ Catalog metric — trusted definition, self-check skipped.")
    elif result.stage == "self_check" and not result.ok:
        st.warning(f"⚠ Self-check flagged this answer — {result.self_check_reason}")
    elif result.ok and result.self_check_reason:
        st.success(f"✓ Self-check passed — {result.self_check_reason}")

    for w in result.warnings:
        st.warning("⚠ " + w)


def render_clarification(result, idx: int) -> None:
    st.markdown(f"❓ {result.clarify_question}")
    cols = st.columns(len(result.clarify_options) or 1)
    for i, opt in enumerate(result.clarify_options):
        if cols[i].button(opt, key=f"opt_{idx}_{i}"):
            st.session_state.queued = opt


# --- sidebar ---------------------------------------------------------------

with st.sidebar:
    st.markdown("### 📊 Analytics Q&A")
    nav = st.radio("Navigation", ["Ask a question", "Schema explorer", "Query history"],
                   label_visibility="collapsed")
    st.divider()
    st.caption("RECENT")
    recents = [m["content"] for m in st.session_state.messages if m["role"] == "user"]
    for rq in reversed(recents[-6:]):
        st.caption("• " + (rq[:36] + "…" if len(rq) > 36 else rq))


# --- main views ------------------------------------------------------------

if nav == "Schema explorer":
    st.subheader("Schema explorer")
    st.caption("The 15 tables the agent can query (Pagila).")
    for t, d in TABLE_DESCRIPTIONS.items():
        with st.expander(t):
            st.write(d)

elif nav == "Query history":
    st.subheader("Query history")
    qs = [m["content"] for m in st.session_state.messages if m["role"] == "user"]
    if not qs:
        st.caption("No questions yet.")
    for i, q in enumerate(qs, 1):
        st.write(f"{i}. {q}")

else:  # Ask a question
    st.subheader("Ask a question")
    st.caption("Self-check on · pagila · read-only")

    for idx, m in enumerate(st.session_state.messages):
        if m["role"] == "user":
            with st.chat_message("user"):
                st.write(m["content"])
        else:
            result = m["result"]
            with st.chat_message("assistant"):
                if result.stage == "clarification":
                    render_clarification(result, idx)
                elif result.rows or result.ok:
                    render_answer_card(result, m.get("summary", ""))
                else:
                    st.error(f"Couldn't answer (stopped at {result.stage}): "
                             + "; ".join(result.errors))

    typed = st.chat_input("Ask about rentals, films, customers, payments…")
    prompt = st.session_state.pop("queued", None) or typed
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.spinner("Thinking…"):
            result = answer_question(prompt, history=st.session_state.history)
            summary = ""
            if result.stage == "answer" and result.rows:
                summary = summarize_answer(prompt, result.columns, result.rows)
        st.session_state.messages.append({"role": "agent", "result": result, "summary": summary})
        if result.resolved:
            st.session_state.history.append(result.resolved)
        st.rerun()
