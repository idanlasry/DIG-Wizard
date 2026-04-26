import streamlit as st
import pandas as pd
import json
from datetime import datetime
from profiler import get_dataset_profile
from pm_agent import run_pm_gate
from de_agent import run_de_agent
from researcher_agent import run_researcher_agent
from da_agent import run_da_agent
from switchboard import run_tool


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

    /* Active tab button — highlighted */
    .stButton>button[kind="primary"] {
        background-color: #00ff9f;
        color: #000;
        box-shadow: 0 0 15px #00ff9f;
    }

    /* Download button style */
    .stDownloadButton>button {
        background-color: transparent;
        color: #00ffff;
        border: 1px solid #00ffff;
        text-transform: uppercase;
        width: 100%;
        transition: 0.3s;
    }
    .stDownloadButton>button:hover {
        background-color: #00ffff;
        color: #000;
        box-shadow: 0 0 15px #00ffff;
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
    st.session_state.pm_summary = None  # PM user_message string
    st.session_state.pm_ready = False  # PM ready_to_proceed flag
    st.session_state.report_view = "metadata"  # Active tab in living report
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
    st.session_state.pm_summaries = []      # accumulates all PM user_messages
    st.session_state.research_paths = None
    st.session_state.tool_result = None
    st.session_state.da_findings = None


def add_log(msg, log_type="info"):
    """Adds a timestamped message to the internal log history."""
    st.session_state.history_logs.append(
        {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "type": log_type}
    )


# ==========================================
# 4. REPORT CONTENT BUILDERS
# Separate functions per view — keeps col_report clean.
# ==========================================


def build_metadata_md() -> str:
    """Builds markdown string from raw profiler metadata."""
    if not st.session_state.metadata:
        return "*No metadata available yet.*"
    meta = st.session_state.metadata
    shape = meta["shape"]
    lines = [
        f"# Dataset Metadata",
        f"**Shape:** {shape['rows']:,} rows × {shape['cols']} columns",
        f"**Duplicate rows:** {meta['duplicate_rows']}",
        "",
        "## Columns",
        "| Name | Dtype | Nulls | Null% | Sample Values |",
        "|------|-------|-------|-------|---------------|",
    ]
    for col in meta["columns"]:
        samples = ", ".join(col["sample_values"][:3])
        lines.append(
            f"| {col['name']} | {col['dtype']} | {col['null_count']} "
            f"| {col['null_pct']}% | {samples} |"
        )
    lines += [
        "",
        "## Numeric Summary",
        "| Column | Mean | Std | Min | Max | IQR Outliers |",
        "|--------|------|-----|-----|-----|--------------|",
    ]
    for col, stats in meta["numeric_summary"].items():
        lines.append(
            f"| {col} | {stats['mean']} | {stats['std']} | {stats['min']} "
            f"| {stats['max']} | {stats['outliers_iqr_count']} |"
        )
    return "\n".join(lines)


def build_de_report_md() -> str:
    """Builds markdown string from DE Agent findings."""
    if not st.session_state.de_findings:
        return "*DE Agent has not run yet.*"
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
    return f"""# DE Agent Report

**Quality Score:** {de["quality_score"]}/10 — {de["quality_score_reason"]}

**Dataset:** {de["dataset_summary"]["total_rows"]:,} rows × {de["dataset_summary"]["total_columns"]} columns

## Columns

| Name | Type | Sample |
|------|------|--------|
{"".join(f"| {c['name']} | {c['type']} | {c['sample_value']} |" + chr(10) for c in de["columns"])}

## Issues Detected
{issues_md}

## Outliers Flagged
{outliers_md}
"""


def build_da_findings_md() -> str:
    """Builds markdown string from all accumulated DA Agent findings."""
    if not st.session_state.analysis_results:
        return "*No paths analyzed yet.*"
    sections = []
    for i, item in enumerate(st.session_state.analysis_results, 1):
        path = item.get("path", {})
        da = item.get("da_findings", {})
        insights_md = "\n".join(f"- {x}" for x in da.get("key_insights", []))
        stats_md = "\n".join(
            f"| {s['label']} | {s['value']} | {s['context']} |"
            for s in da.get("supporting_stats", [])
        )
        caveat_md = f"\n> ⚠️ {da['caveats']}" if da.get("caveats") else ""
        sections.append(
            f"## Path {i} — {path.get('title', '?')}\n"
            f"**{da.get('headline', '')}**\n"
            f"{insights_md}\n\n"
            f"| Label | Value | Context |\n"
            f"|-------|-------|---------|"
            f"\n{stats_md}"
            f"{caveat_md}"
        )
    return "# DA Agent Findings\n\n" + "\n\n---\n\n".join(sections)


def build_pm_summary_md() -> str:
    """Builds markdown string from PM Agent summary."""
    if not st.session_state.pm_summary:
        return "*PM Agent has not run yet.*"
    return f"""# PM Agent Summary

{st.session_state.pm_summary}

---
*Generated by DIG Analytics PM Agent — {datetime.now().strftime("%Y-%m-%d %H:%M")}*
"""


def build_pm_summaries_md() -> str:
    """Builds markdown string from all accumulated PM Agent messages."""
    if not st.session_state.pm_summaries:
        return "*No PM updates yet.*"
    sections = []
    for i, msg in enumerate(st.session_state.pm_summaries, 1):
        sections.append(f"## PM Update {i}\n{msg}")
    return "\n\n---\n\n".join(sections)


# ==========================================
# 5. HEADER UI
# ==========================================
st.markdown('<h1 class="cyber-header">DIG_ANALYTICS_V2.0</h1>', unsafe_allow_html=True)
st.divider()

# ==========================================
# 6. THE THREE-COLUMN LAYOUT
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
                st.session_state.report_view = "metadata"
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
        st.success(f"✅ Data loaded: **{len(df):,} rows × {len(df.columns)} cols**")

        # Only show DE button if DE hasn't run yet
        if st.session_state.de_findings is None:
            if st.button("⚡ INITIALIZE_DE_AGENT"):
                add_log("PROFILER: Starting hardcoded scan...", "system")
                try:
                    profile = get_dataset_profile(df)
                    st.session_state.metadata = profile

                    rows = profile["shape"]["rows"]
                    cols_count = profile["shape"]["cols"]
                    dupes = profile["duplicate_rows"]
                    num_count = len(profile["numeric_summary"])
                    cat_count = len(profile["categorical_summary"])

                    add_log(
                        f"PROFILER: Scan complete. {rows}R × {cols_count}C.", "system"
                    )
                    add_log(
                        f"PROFILER: {num_count} numeric, {cat_count} categorical cols."
                    )
                    add_log(f"PROFILER: {dupes} duplicate rows found.")

                    # ── DE AGENT ──────────────────────────────────────
                    add_log("DE_AGENT: Calling DE Agent...", "system")
                    de_response = run_de_agent(profile)

                    if "error" in de_response:
                        add_log(f"DE_ERROR: {de_response['detail']}", "error")
                        st.error(f"DE Agent failed: {de_response['detail']}")
                    else:
                        st.session_state.de_findings = de_response
                        st.session_state.report_view = "de_report"
                        add_log(
                            f"DE_AGENT: Quality score {de_response['quality_score']}/10.",
                            "system",
                        )
                        add_log(
                            f"DE_AGENT: {len(de_response['quality_issues'])} issue(s), {len(de_response['outliers'])} outlier(s)."
                        )

                        # ── PM GATE ────────────────────────────────────
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
                            st.session_state.pm_summary = pm_response["user_message"]
                            st.session_state.pm_summaries.append(pm_response["user_message"])
                            st.session_state.pm_ready = pm_response.get(
                                "ready_to_proceed", False
                            )
                            st.session_state.report_view = "pm_summary"
                            st.rerun()

                except Exception as e:
                    add_log(f"ERROR: Profiler failed — {e}", "error")
                    st.error(f"Profiler error: {e}")

        # DE has already run — show results + actions
        else:
            de = st.session_state.de_findings
            score = de["quality_score"]
            score_color = (
                "#00ff9f" if score >= 7 else "#ffaa00" if score >= 5 else "#ff0055"
            )

            st.markdown(
                f"<div style='font-family:monospace; font-size:1.1rem; margin-bottom:8px;'>"
                f"DE STATUS: <span style='color:{score_color}'>■</span> "
                f"Quality Score <span style='color:{score_color}'>{score}/10</span> — "
                f"{len(de['quality_issues'])} issue(s) · {len(de['outliers'])} outlier(s)"
                f"</div>",
                unsafe_allow_html=True,
            )

            st.markdown("---")

            if st.session_state.pm_ready:
                if st.button("🚀 PROCEED_TO_RESEARCH"):
                    st.session_state.stage = "RESEARCH"
                    st.rerun()
            else:
                st.warning(
                    "⚠️ Quality score too low to proceed. Review DE report before continuing."
                )

    # ── STAGE: RESEARCH ───────────────────────────────────────────────────
    elif st.session_state.stage == "RESEARCH":
        st.markdown("##### 🔬 STEP_03: RESEARCH_PATHS")

        # ── GENERATE PATHS (first visit) ──────────────────────────────────
        if st.session_state.research_paths is None:
            if st.button("⚡ GENERATE_RESEARCH_PATHS"):
                add_log("RESEARCHER: Generating research paths...", "system")
                result = run_researcher_agent(
                    metadata=st.session_state.metadata,
                    de_findings=st.session_state.de_findings,
                )

                if "error" in result:
                    add_log(f"RESEARCHER_ERROR: {result['detail']}", "error")
                    st.error(f"Researcher Agent failed: {result['detail']}")
                else:
                    st.session_state.research_paths = result["paths"]
                    add_log(
                        f"RESEARCHER: {len(result['paths'])} paths generated.", "system"
                    )
                    st.rerun()

        # ── PATH SELECTION UI ─────────────────────────────────────────────
        else:
            paths = st.session_state.research_paths
            st.markdown("**Select a research path to analyze:**")

            for i, path in enumerate(paths):
                with st.container(border=True):
                    st.markdown(f"**{i + 1}. {path['title']}**")
                    st.caption(path["question"])
                    tool_names = " → ".join(
                        t["tool"] for t in path["tool_instructions"]
                    )
                    st.markdown(
                        f"<span style='color:#888; font-size:0.8rem; font-family:monospace'>"
                        f"TOOLS: {tool_names}</span>",
                        unsafe_allow_html=True,
                    )
                    if st.button(f"▶ SELECT PATH {i + 1}", key=f"path_{i}"):
                        st.session_state.current_path = path
                        add_log(f"PATH_SELECTED: {path['title']}", "system")

                        # PM gates transition to ANALYSIS
                        pm_response = run_pm_gate(
                            current_stage="RESEARCH",
                            metadata=st.session_state.metadata,
                            de_findings=st.session_state.de_findings,
                            selected_path=path,
                            previous_findings=st.session_state.analysis_results or None,
                        )

                        if "error" in pm_response:
                            add_log(f"PM_ERROR: {pm_response['detail']}", "error")
                            st.error(f"PM gate failed: {pm_response['detail']}")
                        else:
                            add_log(f"PM: {pm_response['summary_for_log']}", "system")
                            st.session_state.pm_summary = pm_response["user_message"]
                            st.session_state.pm_summaries.append(pm_response["user_message"])
                            st.session_state.stage = "ANALYSIS"
                            st.session_state.report_view = "pm_summary"
                            st.rerun()
    # ── STAGE: ANALYSIS ────────────────────────────────────────────────
    elif st.session_state.stage == "ANALYSIS":
        st.markdown("##### 📊 STEP_04: ANALYSIS")
        path = st.session_state.current_path

        if path is None:
            st.error("No research path selected. Return to RESEARCH.")
        else:
            st.markdown(f"**Path:** {path['title']}")
            st.caption(path["question"])

            # ── RUN TOOLS + DA AGENT (first visit for this path) ──────────
            if st.session_state.da_findings is None:
                if st.button("⚡ RUN_ANALYSIS"):
                    df = st.session_state.raw_data
                    tool_results = []
                    all_ok = True

                    # Sequential Switchboard execution
                    for instruction in path["tool_instructions"]:
                        tool_name = instruction["tool"]
                        add_log(f"SWITCHBOARD: Running {tool_name}...", "system")
                        result = run_tool(instruction, df)

                        if "error" in result:
                            add_log(
                                f"TOOL_ERROR [{tool_name}]: {result['detail']}", "error"
                            )
                            st.error(f"Tool failed: {tool_name} — {result['detail']}")
                            all_ok = False
                            break

                        add_log(f"SWITCHBOARD: {tool_name} complete.", "system")
                        tool_results.append(result)

                    if all_ok and tool_results:
                        st.session_state.tool_result = tool_results

                        # DA Agent interprets all results
                        add_log("DA_AGENT: Interpreting results...", "system")
                        da_response = run_da_agent(path, tool_results)

                        if "error" in da_response:
                            add_log(f"DA_ERROR: {da_response['detail']}", "error")
                            st.error(f"DA Agent failed: {da_response['detail']}")
                        else:
                            st.session_state.da_findings = da_response
                            add_log(f"DA_AGENT: Analysis complete.", "system")

                            # Accumulate in analysis_results
                            st.session_state.analysis_results.append(
                                {
                                    "path": path,
                                    "tool_result": tool_results,
                                    "da_findings": da_response,
                                }
                            )

                            st.session_state.report_view = "da_findings"
                            st.rerun()

            # ── RESULTS DISPLAY ────────────────────────────────────────────
            else:
                da = st.session_state.da_findings

                st.markdown(f"### 🔍 {da['headline']}")
                st.markdown("**Key Insights:**")
                for insight in da["key_insights"]:
                    st.markdown(f"- {insight}")

                st.markdown("**Supporting Stats:**")
                for stat in da["supporting_stats"]:
                    st.markdown(
                        f"- **{stat['label']}:** {stat['value']} — *{stat['context']}*"
                    )

                if da.get("caveats"):
                    st.warning(f"⚠️ {da['caveats']}")

                st.markdown(
                    f"<span style='color:#888; font-size:0.8rem; font-family:monospace'>"
                    f"RECOMMENDED VIZ: {da['recommended_viz']} — {da['viz_rationale']}</span>",
                    unsafe_allow_html=True,
                )

                st.markdown("---")
                if len(st.session_state.analysis_results) < 3:
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("🔄 RUN_ANOTHER_PATH"):
                            # Reset path-level state, return to RESEARCH
                            st.session_state.current_path = None
                            st.session_state.da_findings = None
                            st.session_state.tool_result = None
                            st.session_state.stage = "RESEARCH"
                            st.rerun()
                    with col_b:
                        if st.button("📈 GO_TO_DASHBOARD"):
                            st.session_state.stage = "DASHBOARD"
                            st.rerun()
                else:
                    st.warning("⚠️ 3-path limit reached. Proceed to dashboard for final synthesis.")
                    if st.button("📈 GO_TO_DASHBOARD"):
                        st.session_state.stage = "DASHBOARD"
                        st.rerun()

    # ── STAGE: DASHBOARD (placeholder) ────────────────────────────────
    elif st.session_state.stage == "DASHBOARD":
        st.markdown("##### 📈 STEP_05: DASHBOARD")
        st.info("BI Developer Agent + Plotly rendering coming in Stage 11.")

# --- COLUMN 3: LIVING REPORT ---
with col_report:
    st.markdown("### 📑 LIVING_REPORT")

    # ── TAB TOGGLE BUTTONS ─────────────────────────────────────────────
    tab_cols = st.columns(5)

    with tab_cols[0]:
        if st.button("📋 METADATA", disabled=st.session_state.metadata is None):
            st.session_state.report_view = "metadata"
            st.rerun()

    with tab_cols[1]:
        if st.button("🔧 DE REPORT", disabled=st.session_state.de_findings is None):
            st.session_state.report_view = "de_report"
            st.rerun()

    with tab_cols[2]:
        if st.button("💬 PM SUMMARY", disabled=st.session_state.pm_summary is None):
            st.session_state.report_view = "pm_summary"
            st.rerun()

    with tab_cols[3]:
        if st.button("📊 DA FINDINGS", disabled=len(st.session_state.analysis_results) == 0):
            st.session_state.report_view = "da_findings"
            st.rerun()

    with tab_cols[4]:
        if st.button("💬 PM LOG", disabled=len(st.session_state.pm_summaries) == 0):
            st.session_state.report_view = "pm_log"
            st.rerun()

    # ── CONTENT RENDER ─────────────────────────────────────────────────
    view = st.session_state.report_view

    if view == "metadata":
        content_md = build_metadata_md()
    elif view == "de_report":
        content_md = build_de_report_md()
    elif view == "pm_summary":
        content_md = build_pm_summary_md()
    elif view == "da_findings":
        content_md = build_da_findings_md()
    elif view == "pm_log":
        content_md = build_pm_summaries_md()
    else:
        content_md = st.session_state.master_report

    with st.container(height=550, border=True):
        st.markdown(content_md)

    # ── DOWNLOAD BUTTON ────────────────────────────────────────────────
    view_label = {
        "metadata": "metadata",
        "de_report": "de_report",
        "pm_summary": "pm_summary",
        "da_findings": "da_findings",
        "pm_log": "pm_log",
    }.get(view, "report")
    st.download_button(
        label=f"⬇️ DOWNLOAD_{view_label.upper()}.MD",
        data=content_md,
        file_name=f"DIG_{view_label}_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
        mime="text/markdown",
    )

# ==========================================
# 7. FOOTER / SYSTEM STATUS
# ==========================================
st.divider()
status_cols = st.columns(4)
status_cols[0].caption(f"STAGE: {st.session_state.stage}")
status_cols[1].caption(f"VIEW: {st.session_state.report_view}")
status_cols[2].caption(
    f"ROWS: {len(st.session_state.raw_data) if st.session_state.raw_data is not None else 0}"
)
status_cols[3].caption("MODEL: CLAUDE-HAIKU-4")
