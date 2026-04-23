import streamlit as st
import pandas as pd
import json
from datetime import datetime

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
# This section ensures that data persists when the script reruns.
if "initialized" not in st.session_state:
    st.session_state.initialized = True
    st.session_state.stage = (
        "START"  # START -> AUDIT -> RESEARCH -> ANALYSIS -> DASHBOARD
    )
    st.session_state.raw_data = None
    st.session_state.metadata = None
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
    st.session_state.analysis_results = []  # Stores all previous path outcomes


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
# 1 part Log : 2 parts Interaction : 1 part Report
col_terminal, col_main, col_report = st.columns([1, 2, 1])

# --- COLUMN 1: TERMINAL (The Agent Activity Logs) ---
with col_terminal:
    st.markdown("### 🖥️ SYSTEM_LOGS")
    with st.container(height=500, border=True):
        for log in st.session_state.history_logs:
            # Color logic for different log types
            color = "#00ff9f" if log["type"] == "system" else "#ffffff"
            if log["type"] == "error":
                color = "#ff0055"

            st.markdown(
                f"<div class='terminal-font'><b>[{log['time']}]</b> <span style='color:{color}'>{log['msg']}</span></div>",
                unsafe_allow_html=True,
            )

# --- COLUMN 2: COMMAND CENTER (User Interaction Area) ---
with col_main:
    st.markdown("### 🕹️ COMMAND_CENTER")

    # Logic Router based on the 'Stage'
    if st.session_state.stage == "START":
        st.markdown("##### 📥 STEP_01: DATA_INTAKE")
        uploaded_file = st.file_uploader("UPLOAD_CSV_FILE", type="csv")

        if uploaded_file is not None:
            try:
                df = pd.read_csv(uploaded_file)
                st.session_state.raw_data = df
                st.session_state.stage = "AUDIT"
                add_log(f"DATA_INGESTED: {len(df)} rows, {len(df.columns)} columns.")
                st.rerun()
            except Exception as e:
                st.error(f"Error loading file: {e}")
                add_log(f"ERROR: Failed to read CSV. {e}", "error")
elif st.session_state.stage == "AUDIT":
        from profiler import get_dataset_profile

        st.markdown("##### 🔍 STEP_02: DATA_AUDIT")
        df = st.session_state.raw_data
        st.write(f"Data source active: **{len(df)} rows × {len(df.columns)} cols**")

        if st.button("INITIALIZE_DE_AGENT"):
            add_log("PROFILER: Starting hardcoded scan...", "system")

            try:
                profile = get_dataset_profile(df)
                st.session_state.metadata = profile

                # Log key facts into the terminal
                rows = profile["shape"]["rows"]
                cols = profile["shape"]["cols"]
                dupes = profile["duplicate_rows"]
                is_sample = profile["is_sample"]
                num_count = len(profile["numeric_summary"])
                cat_count = len(profile["categorical_summary"])

                add_log(f"PROFILER: Scan complete. {rows}R × {cols}C.", "system")
                add_log(f"PROFILER: {num_count} numeric cols, {cat_count} categorical cols.")
                add_log(f"PROFILER: {dupes} duplicate rows found.")
                if is_sample:
                    add_log("PROFILER: Large dataset — sampled (250 head + 250 tail + 500 random).")
                else:
                    add_log("PROFILER: Full dataset used (under 5k rows).")

                st.session_state.stage = "RESEARCH"
                st.rerun()

            except Exception as e:
                add_log(f"ERROR: Profiler failed — {e}", "error")
                st.error(f"Profiler error: {e}")

            except Exception as e:
                add_log(f"ERROR: Profiler failed — {e}", "error")
                st.error(f"Profiler error: {e}")
    # (Placeholders for Research, Analysis, and Dashboard stages will go here)

# --- COLUMN 3: THE ARCHIVE (The Consolidated Living Report) ---
with col_report:
    st.markdown("### 📑 LIVING_REPORT")
    # This container displays the synthesized findings
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
status_cols[3].caption("MODEL: CLAUDE-3.5-SONNET")
