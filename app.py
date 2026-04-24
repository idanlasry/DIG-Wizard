import streamlit as st
import pandas as pd
import json
from datetime import datetime
from profiler import get_dataset_profile
from pm_agent import run_pm_gate
from de_agent import run_de_agent

# ==========================================
# 1. PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="DIG Analytics v2.0",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ==========================================
# 2. CYBERPUNK STYLING (CSS)
# ==========================================
st.markdown(
    """
    <style>
    /* Main Background & Text */
    .stApp {
        background-color: #050505;
        color: #00ff9f;
    }

    /* Neon Borders for Container sections */
    [data-testid="stVerticalBlock"] > div:has(div.stExpander),
    [data-testid="stVerticalBlock"] > div:has(div.stContainer) {
        border: 1px solid #00ff9f;
        padding: 10px;
        border-radius: 5px;
        background: rgba(10, 10, 10, 0.9);
        box-shadow: 0 0 10px rgba(0, 255, 159, 0.1);
    }

    /* Standardizes font to monospaced for that 'Terminal' feel */
    .terminal-font {
        font-family: 'Fira Code', 'Courier New', monospace;
        font-size: 0.85rem;
    }

    /* Cyber Header styling */
    .cyber-header {
        font-family: 'Orbitron', sans-serif;
        text-transform: uppercase;
        letter-spacing: 3px;
        color: #00ff9f;
        text-shadow: 0 0 10px #00ff9f;
        margin-bottom: 20px;
    }

    /* Style for buttons to look more 'Cyber' */
    .stButton>button {
        background-color: transparent;
        color: #00ff9f;
        border: 1px solid #00ff9f;
        text-transform: uppercase;
        width: 100%;
        transition: 0.3s;
    }
    .stButton>button:hover {
        background-color: #00ff9f;
        color: #000;
        box-shadow: 0 0 15px #00ff9f;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ==========================================
# 3. BRAIN: SESSION STATE INITIALIZATION
# ==========================================
if "initialized" not in st.session_state:
    st.session_state.initialized = True
    st.session_state.stage = "START"
    st.session_state.raw_data = None
    st.session_state.metadata = None
    st.session_state.de_findings = None
    st.session_state.history_logs = [
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "msg": "SYS_READY: Initialization complete.",
            "type": "system",
        }
    ]
    st.session_state.master_report = (
        "# DIG Analytics Executive Summary\n*Awaiting data ingestion...*"
    )
    st.session_state.current_path = None
    st.session_state.analysis_results = []


def add_log(msg, log_type="info"):
    """Adds a timestamped message to the internal log history."""
    st.session_state.history_logs.append(
        {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "type": log_type}
    )


# ==========================================
# 4. HEADER UI
# ==========================================
st.markdown('<h1 class="cyber-header">DIG_ANALYTICS_V2.0</h1>', unsafe_allow_html=True)
st.divider()

# ==========================================
# 5. THE THREE-COLUMN LAYOUT
# ==========================================
col_terminal, col_main, col_report = st.columns([1, 2, 2])

# --- COLUMN 1: TERMINAL ---
with col_terminal:
    st.markdown("### 🖥️ SYSTEM_LOGS")
    with st.container(height=500, border=True):
        for log in st.session_state.history_logs:
            color = "#00ff9f" if log["type"] == "system" else "#ffffff"
            if log["type"] == "error":
                color = "#ff0055"

            st.markdown(
                f"<div class='terminal-font'><b>[{log['time']}]</b> "
                f"<span style='color:{color}'>{log['msg']}</span></div>",
                unsafe_allow_html=True,
            )

# --- COLUMN 2: COMMAND CENTER ---
with col_main:
    st.markdown("### 🕹️ COMMAND_CENTER")

    # ── STAGE: START ───────────────────────────────────────────────────
    if st.session_state.stage == "START":
        st.markdown("##### 📥 STEP_01: DATA_INTAKE")
        uploaded_file = st.file_uploader("UPLOAD_CSV_FILE", type="csv")

        if uploaded_file is not None:
            try:
                df = pd.read_csv(uploaded_file)
                st.session_state.raw_data = df
                st.session_state.stage = "AUDIT"
                add_log(
                    f"DATA_INGESTED: {len(df)} rows, {len(df.columns)} columns.",
                    "system",
                )
                st.rerun()
            except Exception as e:
                st.error(f"Error loading file: {e}")
                add_log(f"ERROR: Failed to read CSV. {e}", "error")

    # ── STAGE: AUDIT ───────────────────────────────────────────────────
    elif st.session_state.stage == "AUDIT":
        st.markdown("##### 🔍 STEP_02: DATA_AUDIT")
        df = st.session_state.raw_data
        st.write(f"Data source active: **{len(df)} rows × {len(df.columns)} cols**")

        if st.button("INITIALIZE_DE_AGENT"):
            add_log("PROFILER: Starting hardcoded scan...", "system")

            try:
                profile = get_dataset_profile(df)
                st.session_state.metadata = profile

                rows = profile["shape"]["rows"]
                cols_count = profile["shape"]["cols"]
                dupes = profile["duplicate_rows"]
                num_count = len(profile["numeric_summary"])
                cat_count = len(profile["categorical_summary"])

                add_log(f"PROFILER: Scan complete. {rows}R × {cols_count}C.", "system")
                add_log(
                    f"PROFILER: {num_count} numeric cols, {cat_count} categorical cols."
                )
                add_log(f"PROFILER: {dupes} duplicate rows found.")

                # ── DE AGENT ──────────────────────────────────────────
                add_log("DE_AGENT: Calling DE Agent...", "system")
                de_response = run_de_agent(profile)

                if "error" in de_response:
                    add_log(f"DE_ERROR: {de_response['detail']}", "error")
                    st.error(f"DE Agent failed: {de_response['detail']}")
                else:
                    st.session_state.de_findings = de_response
                    add_log(
                        f"DE_AGENT: Quality score {de_response['quality_score']}/10.",
                        "system",
                    )
                    add_log(
                        f"DE_AGENT: {len(de_response['quality_issues'])} issue(s), {len(de_response['outliers'])} outlier(s)."
                    )

                    # ── PM GATE ────────────────────────────────────────
                    add_log("PM_GATE: Calling PM Agent at AUDIT...", "system")
                    pm_response = run_pm_gate(
                        current_stage="AUDIT",
                        metadata=profile,
                        de_findings=st.session_state.de_findings,
                    )

                    if "error" in pm_response:
                        add_log(f"PM_ERROR: {pm_response['detail']}", "error")
                        st.error(f"PM Agent failed: {pm_response['detail']}")
                    else:
                        add_log(f"PM: {pm_response['summary_for_log']}", "system")
                        st.info(pm_response["user_message"])

                        # ── SEED LIVING REPORT ─────────────────────────
                        de = st.session_state.de_findings
                        issues_md = (
                            "\n".join(
                                f"- **{i['issue']}** ({i['affected_column']}): {i['detail']}"
                                for i in de["quality_issues"]
                            )
                            or "_None detected._"
                        )
                        outliers_md = (
                            "\n".join(
                                f"- **{o['column']}** — {o['value']} ({o['reason']})"
                                for o in de["outliers"]
                            )
                            or "_None detected._"
                        )

                        st.session_state.master_report = f"""# DIG Analytics Executive Summary

## Dataset Audit

## Dataset Audit
**PM Assessment:** {pm_response["user_message"]}


**Quality Score:** {de["quality_score"]}/10 — {de["quality_score_reason"]}

**Dataset:** {de["dataset_summary"]["total_rows"]:,} rows × {de["dataset_summary"]["total_columns"]} columns

### Issues Detected
{issues_md}

### Outliers Flagged
{outliers_md}

---
*Awaiting research path selection...*
"""
                        if pm_response.get("stage_transition"):
                            st.session_state.stage = pm_response["stage_transition"]
                            st.rerun()

            except Exception as e:
                add_log(f"ERROR: Profiler failed — {e}", "error")
                st.error(f"Profiler error: {e}")

    # ── STAGE: RESEARCH (placeholder) ─────────────────────────────────
    elif st.session_state.stage == "RESEARCH":
        st.markdown("##### 🔬 STEP_03: RESEARCH_PATHS")
        st.info("Researcher Agent logic coming in Stage 9.")

    # ── STAGE: ANALYSIS (placeholder) ─────────────────────────────────
    elif st.session_state.stage == "ANALYSIS":
        st.markdown("##### 📊 STEP_04: ANALYSIS")
        st.info("Stats Expert + DA Agent logic coming in Stage 10.")

    # ── STAGE: DASHBOARD (placeholder) ────────────────────────────────
    elif st.session_state.stage == "DASHBOARD":
        st.markdown("##### 📈 STEP_05: DASHBOARD")
        st.info("BI Developer Agent + Plotly rendering coming in Stage 11.")

# --- COLUMN 3: LIVING REPORT ---
with col_report:
    st.markdown("### 📑 LIVING_REPORT")
    with st.container(height=600, border=True):
        st.markdown(st.session_state.master_report)

# ==========================================
# 6. FOOTER / SYSTEM STATUS
# ==========================================
st.divider()
status_cols = st.columns(4)
status_cols[0].caption(f"STAGE: {st.session_state.stage}")
status_cols[1].caption(f"INITIALIZED: {st.session_state.initialized}")
status_cols[2].caption(
    f"ROWS: {len(st.session_state.raw_data) if st.session_state.raw_data is not None else 0}"
)
status_cols[3].caption("MODEL: CLAUDE-SONNET-4")
