import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
from core.profiler import get_dataset_profile
from core.switchboard import run_tool
from agents.pm_agent import run_pm_gate
from agents.de_agent import run_de_agent
from agents.researcher_agent import run_researcher_agent
from agents.da_agent import run_da_agent
from core.cross_path_aggregator import build_cross_path_summary
from agents.bi_agent import run_bi_agent
from agents.synthesis_agent import run_synthesis_agent
import plotly.graph_objects as go
import os

if "ANTHROPIC_API_KEY" not in os.environ:
    os.environ["ANTHROPIC_API_KEY"] = st.secrets.get("ANTHROPIC_API_KEY", "")


def read_uploaded_file(file):
    name = file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(file), None
    if name.endswith(".tsv"):
        return pd.read_csv(file, sep="\t"), None
    if name.endswith(".json"):
        df = pd.read_json(file)
        flat_cols = [
            c for c in df.columns
            if not df[c].dropna().apply(lambda x: isinstance(x, (dict, list))).any()
        ]
        dropped = set(df.columns) - set(flat_cols)
        if dropped:
            st.warning(f"JSON: nested columns dropped (not profileable): {', '.join(dropped)}")
        return df[flat_cols], None
    if name.endswith(".parquet"):
        return pd.read_parquet(file), None
    if name.endswith((".xlsx", ".xls")):
        xl = pd.ExcelFile(file)
        if len(xl.sheet_names) == 1:
            return xl.parse(xl.sheet_names[0]), None
        return None, xl.sheet_names
    raise ValueError(f"Unsupported file type: {file.name}")


# ==========================================
# 1. PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="DIG Analytics Wizard",
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
    st.session_state.stage = "WELCOME"
    st.session_state.raw_data = None
    st.session_state.metadata = None
    st.session_state.de_findings = None
    st.session_state.de_running = False
    st.session_state.pm_ready = False  # PM ready_to_proceed flag
    st.session_state.report_view = "metadata"  # Active tab in living report
    st.session_state.history_logs = [
        {
            "time": (datetime.now() + timedelta(hours=3)).strftime("%H:%M:%S"),
            "msg": "System ready.",
            "type": "system",
        }
    ]
    st.session_state.master_report = (
        "# DIG Analytics Executive Summary\n*Awaiting data ingestion...*"
    )
    st.session_state.current_path = None
    st.session_state.cross_path_summary = {}
    st.session_state.analysis_results = []
    st.session_state.pm_summaries = []  # accumulates all PM user_messages
    st.session_state.research_paths = None
    st.session_state.primary_metric = None
    st.session_state.tool_result = None
    st.session_state.da_findings = None
    st.session_state.chart_configs = None
    st.session_state.synthesis = None
    st.session_state.pm_final_summary = None
    st.session_state.api_call_count = 0
    st.session_state.total_input_tokens = 0
    st.session_state.total_output_tokens = 0
    st.session_state.estimated_cost_usd = 0.0
    st.session_state.user_interest_choice = "none"  # "none" | "yes"
    st.session_state.user_interest_text = ""
    st.session_state.user_interest_path = None

print(
    f"[RERUN] Stage: {st.session_state.stage} | "
    f"API calls: {st.session_state.api_call_count} | "
    f"Tokens in/out: {st.session_state.total_input_tokens}/{st.session_state.total_output_tokens} | "
    f"Est. cost: ${st.session_state.estimated_cost_usd:.4f}"
)


def add_log(msg, log_type="info"):
    """Adds a timestamped message to the internal log history."""
    st.session_state.history_logs.append(
        {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "type": log_type}
    )


def build_html_report(
    pm_final_summary: str,
    chart_configs: dict,
    synthesis: dict,
    metadata: dict,
    de_findings: dict,
    analysis_results: list,
) -> str:
    kpis = chart_configs["kpis"]
    charts = chart_configs["charts"]
    narrative = synthesis["narrative"]
    recommendations = synthesis["recommendations"]

    kpi_items = "".join(
        f"<div class='kpi'><strong>{k['label']}</strong>"
        f"<div class='value'>{k['value']}</div>"
        f"<div class='context'>{k['context']}</div></div>"
        for k in kpis
    )

    # Dataset snapshot stats
    total_customers = metadata["shape"]["rows"]
    total_cols = metadata["shape"]["cols"]
    duplicate_rows = metadata["duplicate_rows"]
    quality_score = de_findings.get("quality_score", "N/A")
    pm = st.session_state.get("primary_metric")
    if pm is None:
        # Fallback: detect binary column (min=0, max=1) from metadata
        num_summary = metadata.get("numeric_summary", {})
        for col, stats in num_summary.items():
            if stats.get("min") == 0 and stats.get("max") == 1:
                rate = stats.get("mean", 0) * 100
                pm = {
                    "label": col.replace("_", " ").title(),
                    "column": col,
                    "rate_pct": rate,
                }
                break
    snapshot_items = [
        ("Total Rows", f"{total_customers:,}"),
        ("Features", total_cols),
        ("Duplicate Rows", duplicate_rows),
        ("Data Quality Score", quality_score),
    ]
    if pm:
        snapshot_items.insert(2, (pm["label"], f"{pm['rate_pct']:.1f}%"))

    snapshot_cards = "".join(
        f"<div class='snapshot-card'><div class='label'>{label}</div><div class='val'>{value}</div></div>"
        for label, value in snapshot_items
    )

    chart_blocks = []
    for i, chart in enumerate(charts):
        chart_type = chart["chart_type"]
        if chart_type == "bar":
            trace = go.Bar(x=chart["x"], y=chart["y"], marker_color="#00ff9f")
        elif chart_type == "line":
            trace = go.Scatter(
                x=chart["x"],
                y=chart["y"],
                mode="lines",
                line=dict(color="#00ff9f", width=2),
            )
        elif chart_type == "scatter":
            trace = go.Scatter(
                x=chart["x"],
                y=chart["y"],
                mode="markers",
                marker=dict(color="#00ff9f", size=6),
            )
        else:
            trace = go.Heatmap(z=[chart["y"]], colorscale="Viridis")
        fig = go.Figure(data=[trace])
        fig.update_layout(
            title=chart["title"],
            xaxis_title=chart["x_label"],
            yaxis_title=chart["y_label"],
            height=280,
            margin=dict(l=40, r=20, t=40, b=40),
            paper_bgcolor="#ffffff",
            plot_bgcolor="#f9f9f9",
            font=dict(color="#111111", size=10),
        )
        # Plotly CDN is loaded in <head>; all chart divs use False to avoid re-bundling
        fig_html = fig.to_html(full_html=False, include_plotlyjs=False)
        explanation = chart.get("explanation", "")
        headline = ""
        if i < len(analysis_results):
            headline = analysis_results[i].get("da_findings", {}).get("headline", "")
        chart_blocks.append(
            f"<div class='chart-block'><h3>{headline}</h3>{fig_html}"
            f"<em>{explanation}</em></div>"
        )

    recs_html = (
        '<ul class="recs">'
        + "".join(f"<li>{r}</li>" for r in recommendations)
        + "</ul>"
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>DIG Analytics Report</title>
<script src="https://cdn.plot.ly/plotly-3.5.0.min.js"></script>
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#ffffff;color:#111111;padding:2rem 3rem;max-width:1400px;margin:0 auto;font-size:0.85rem}}
h1{{font-size:1.4rem;margin-bottom:0.3rem}}
h2{{font-size:1rem;margin:1rem 0 0.4rem;border-bottom:1px solid #ddd;padding-bottom:0.2rem}}
h3{{font-size:0.85rem;margin:0.3rem 0}}
p{{margin:0.3rem 0;font-size:0.8rem;line-height:1.4}}
.kpi-row{{display:flex;gap:0.6rem;flex-wrap:nowrap;margin:0.5rem 0}}
.kpi{{border:1px solid #ddd;border-radius:4px;padding:0.5rem 0.8rem;flex:1;min-width:0}}
.kpi strong{{font-size:0.75rem;color:#555;display:block}}
.kpi .value{{font-size:1.1rem;font-weight:bold;margin:0.1rem 0}}
.kpi .context{{font-size:0.7rem;color:#666}}
.snapshot-row{{display:flex;gap:0.6rem;margin:0.5rem 0}}
.snapshot-card{{border:1px solid #eee;border-radius:4px;padding:0.4rem 0.8rem;flex:1;text-align:center;background:#f9f9f9}}
.snapshot-card .label{{font-size:0.7rem;color:#888}}
.snapshot-card .val{{font-size:1rem;font-weight:bold}}
.chart-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:0.5rem 0}}
.chart-block{{border:1px solid #eee;border-radius:4px;padding:0.5rem}}
.chart-block em{{font-size:0.72rem;color:#555;display:block;margin-top:0.3rem}}
.recs{{margin:0.5rem 0;padding-left:1.2rem}}
.recs li{{font-size:0.78rem;margin-bottom:0.3rem;line-height:1.4}}
.narrative{{background:#f5f5f5;border-left:3px solid #333;padding:0.6rem 1rem;font-size:0.8rem;line-height:1.5;margin:0.5rem 0}}
</style></head><body>
<h1>DIG Analytics Executive Report</h1>
<h2>Executive Summary</h2><div class="narrative">{pm_final_summary}</div>
<h2>Dataset Snapshot</h2><div class="snapshot-row">{snapshot_cards}</div>
<h2>Key Performance Indicators</h2><div class="kpi-row">{kpi_items}</div>
<h2>Dashboard Analysis</h2><div class="chart-grid">{"".join(chart_blocks)}</div>
<h2>Strategic Narrative</h2><div class="narrative">{narrative}</div>
<h2>Recommendations</h2>{recs_html}
</body></html>"""


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
    """Builds markdown string from Data Engineer findings."""
    if not st.session_state.de_findings:
        return "*Data quality review not yet run.*"
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
    return f"""# Data Quality Report

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
    return "# Analysis Findings\n\n" + "\n\n---\n\n".join(sections)


def build_pm_summary_md() -> str:
    """Builds markdown string from Product Manager summary."""
    if not st.session_state.pm_summaries:
        return "*No pipeline summary yet.*"
    return f"""# Pipeline Summary

{st.session_state.pm_summaries[-1]}

---
*Generated by DIG Analytics — {datetime.now().strftime("%Y-%m-%d %H:%M")}*
"""


def build_pm_summaries_md() -> str:
    """Builds markdown string from all accumulated Product Manager messages."""
    if not st.session_state.pm_summaries:
        return "*No activity log yet.*"
    sections = []
    for i, msg in enumerate(st.session_state.pm_summaries, 1):
        sections.append(f"## Update {i}\n{msg}")
    return "\n\n---\n\n".join(sections)


# ==========================================
# 5. HEADER UI
# ==========================================
st.markdown(
    '<h1 class="cyber-header">DIG ANALYTICS WIZARD</h1>', unsafe_allow_html=True
)
st.divider()

# ==========================================
# 6. THE THREE-COLUMN LAYOUT
# ==========================================
col_terminal, col_main, col_report = st.columns([1, 2, 2])

# --- COLUMN 1: TERMINAL ---
with col_terminal:
    st.markdown("### 🖥️ SYSTEM LOGS")
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
    st.markdown("### 🕹️ COMMAND CENTER")

    # ── STAGE: WELCOME ─────────────────────────────────────────────────
    if st.session_state.stage == "WELCOME":
        st.markdown(
            """
<div style='border:1px solid #00ff9f33; border-radius:6px; padding:20px 24px; margin-bottom:16px; background:rgba(0,255,159,0.04)'>
<div style='color:#00ff9f; font-size:0.75rem; font-family:monospace; letter-spacing:1px; margin-bottom:12px'>WELCOME</div>
<div style='font-size:0.95rem; line-height:1.7; font-family:monospace; color:#fff; margin-bottom:8px'>
Hello, fellow analyst! 👋
</div>
<div style='font-size:0.83rem; line-height:1.8; font-family:monospace; color:#ccc'>
<b style='color:#fff'>DIG</b> is an AI-powered data analysis platform built for you — no SQL, no code, just answers.<br>
Upload any data file and a team of specialized AI agents will guide you from raw data to executive insights.
</div>
</div>

<div style='border:1px solid #00ff9f33; border-radius:6px; padding:16px 20px; margin-bottom:16px; background:rgba(0,255,159,0.03)'>
<div style='color:#00ff9f; font-size:0.75rem; font-family:monospace; letter-spacing:1px; margin-bottom:12px'>THE DIG FRAMEWORK</div>
<div style='font-size:0.83rem; line-height:2.2; font-family:monospace; color:#ccc'>
<span style='color:#00ff9f; font-size:1rem; font-weight:bold'>D</span> &nbsp;<b style='color:#fff'>Description</b> &nbsp;—&nbsp; What is the data? &nbsp;<span style='color:#666'>Schema · Quality · Outliers</span><br>
<span style='color:#00ff9f; font-size:1rem; font-weight:bold'>I</span> &nbsp;<b style='color:#fff'>Introspection</b> &nbsp;—&nbsp; What does it mean? &nbsp;<span style='color:#666'>Patterns · Correlations · Trends</span><br>
<span style='color:#00ff9f; font-size:1rem; font-weight:bold'>G</span> &nbsp;<b style='color:#fff'>Goal Setting</b> &nbsp;—&nbsp; What should we do? &nbsp;<span style='color:#666'>KPIs · Strategy · Visualizations</span>
</div>
</div>

<div style='border:1px solid #00ff9f33; border-radius:6px; padding:16px 20px; margin-bottom:20px; background:rgba(0,255,159,0.03)'>
<div style='color:#00ff9f; font-size:0.75rem; font-family:monospace; letter-spacing:1px; margin-bottom:12px'>HOW IT WORKS</div>
<div style='font-size:0.83rem; line-height:2.2; font-family:monospace; color:#ccc'>
🔧 <b style='color:#fff'>Data Engineer</b> &nbsp;— Reviews your data quality and readiness<br>
🔬 <b style='color:#fff'>Research Analyst</b> &nbsp;— Suggests research questions to explore<br>
📊 <b style='color:#fff'>Data Analyst</b> &nbsp;— Analyzes each research question in depth<br>
📈 <b style='color:#fff'>BI Developer</b> &nbsp;— Builds your final executive dashboard<br>
🤝 <b style='color:#00ff9f'>Product Manager</b> &nbsp;— Guides and summarizes every step
</div>
</div>
""",
            unsafe_allow_html=True,
        )
        if st.button("🚀 Ready to Analyze Your Data", use_container_width=True):
            st.session_state.stage = "START"
            st.rerun()

    # ── STAGE: START ───────────────────────────────────────────────────
    elif st.session_state.stage == "START":
        st.markdown("##### 📥 STEP 01: DATA INTAKE")

        if st.button(
            "🏦 USE BANK DEMO DATA", help="Load the Bank Churn sample dataset"
        ):
            try:
                df = pd.read_csv("practice_data/Bank_Churn.csv")
                st.session_state.raw_data = df
                profile = get_dataset_profile(df)
                st.session_state.metadata = profile
                add_log(
                    f"Profiler: Scan complete — {profile['shape']['rows']} rows × {profile['shape']['cols']} columns.",
                    "system",
                )
                add_log(
                    f"Profiler: {len(profile['numeric_summary'])} numeric, {len(profile['categorical_summary'])} categorical columns."
                )
                add_log(f"Profiler: {profile['duplicate_rows']} duplicate rows found.")
                st.session_state.stage = "AUDIT"
                st.session_state.report_view = "metadata"
                add_log(
                    f"Demo data loaded: Bank Churn dataset — {len(df)} rows, {len(df.columns)} columns.",
                    "system",
                )
                st.rerun()
            except Exception as e:
                st.error(f"Error loading demo data: {e}")
                add_log(f"ERROR: Failed to read demo CSV. {e}", "error")

        st.markdown("— or —")
        uploaded_file = st.file_uploader(
            "UPLOAD DATA FILE",
            type=["csv", "tsv", "xlsx", "xls", "json", "parquet"],
        )
        st.caption("Accepted formats: CSV · TSV · Excel (.xlsx / .xls) · JSON (flat/records) · Parquet")

        if uploaded_file is not None:
            try:
                df, sheet_names = read_uploaded_file(uploaded_file)

                if sheet_names is not None:
                    chosen_sheet = st.selectbox(
                        "This workbook has multiple sheets. Select one to load:",
                        sheet_names,
                    )
                    if st.button("Load selected sheet"):
                        uploaded_file.seek(0)
                        df = pd.read_excel(uploaded_file, sheet_name=chosen_sheet)
                    else:
                        df = None

                if df is not None:
                    st.session_state.raw_data = df
                    profile = get_dataset_profile(df)
                    st.session_state.metadata = profile
                    add_log(
                        f"Profiler: Scan complete — {profile['shape']['rows']} rows × {profile['shape']['cols']} columns.",
                        "system",
                    )
                    add_log(
                        f"Profiler: {len(profile['numeric_summary'])} numeric, {len(profile['categorical_summary'])} categorical columns."
                    )
                    add_log(f"Profiler: {profile['duplicate_rows']} duplicate rows found.")
                    st.session_state.stage = "AUDIT"
                    st.session_state.report_view = "metadata"
                    add_log(
                        f"Data loaded: {len(df)} rows, {len(df.columns)} columns.",
                        "system",
                    )
                    st.rerun()

            except Exception as e:
                st.error(f"Could not read file '{uploaded_file.name}': {e}")
                add_log(f"ERROR: Failed to read uploaded file. {e}", "error")

    # ── STAGE: AUDIT ───────────────────────────────────────────────────
    elif st.session_state.stage == "AUDIT":
        st.markdown("##### 🔍 STEP 02: DATA AUDIT")
        df = st.session_state.raw_data
        st.success(f"✅ Data loaded: **{len(df):,} rows × {len(df.columns)} cols**")

        # Only show DE button if DE hasn't run yet
        if st.session_state.de_findings is None:
            if st.session_state.de_running:
                st.button("⚡ Run Data Quality Audit", disabled=True)
                with st.spinner("Data Engineer reviewing your data..."):
                    try:
                        profile = st.session_state.metadata

                        # ── DE AGENT ──────────────────────────────────────
                        add_log("Data Engineer: Reviewing data quality...", "system")
                        st.session_state.api_call_count += 1
                        de_response = run_de_agent(profile)

                        if "error" in de_response:
                            add_log(
                                f"Data Engineer Error: {de_response['detail']}", "error"
                            )
                            print(f"[ERROR] DE Agent: {de_response['detail']}")
                            st.session_state.de_running = False
                            st.error(
                                "⚠️ Data quality review failed. Try again or check the activity log."
                            )
                        else:
                            st.session_state.de_findings = de_response
                            st.session_state.report_view = "de_report"
                            add_log(
                                f"Data Engineer: Quality score {de_response['quality_score']}/10.",
                                "system",
                            )
                            add_log(
                                f"Data Engineer: {len(de_response['quality_issues'])} issue(s), {len(de_response['outliers'])} outlier(s)."
                            )

                            # ── PM GATE ────────────────────────────────────
                            add_log(
                                "Product Manager: Reviewing audit findings...", "system"
                            )
                            st.session_state.api_call_count += 1
                            pm_response = run_pm_gate(
                                current_stage="AUDIT",
                                metadata=profile,
                                de_findings=st.session_state.de_findings,
                            )

                            if "error" in pm_response:
                                add_log(
                                    f"Product Manager Error: {pm_response['detail']}",
                                    "error",
                                )
                                print(f"[ERROR] PM Agent: {pm_response['detail']}")
                                st.session_state.de_running = False
                                st.error(
                                    "⚠️ Product Manager step failed. Try again or check the activity log."
                                )
                            else:
                                add_log(
                                    f"Product Manager: {pm_response['summary_for_log']}",
                                    "system",
                                )
                                st.session_state.pm_summaries.append(
                                    pm_response["user_message"]
                                )
                                st.session_state.pm_ready = pm_response.get(
                                    "ready_to_proceed", False
                                )
                                st.session_state.report_view = "pm_summary"
                                st.session_state.de_running = False
                                st.rerun()

                    except Exception as e:
                        st.session_state.de_running = False
                        add_log(f"ERROR: Profiler failed — {e}", "error")
            elif st.button("⚡ Run Data Quality Audit"):
                st.session_state.de_running = True
                st.rerun()

        # DE has already run — show results + actions
        else:
            de = st.session_state.de_findings
            score = de["quality_score"]
            score_color = (
                "#00ff9f" if score >= 7 else "#ffaa00" if score >= 5 else "#ff0055"
            )

            st.markdown(
                f"<div style='font-family:monospace; font-size:1.1rem; margin-bottom:8px;'>"
                f"Data Quality: <span style='color:{score_color}'>■</span> "
                f"Quality Score <span style='color:{score_color}'>{score}/10</span> — "
                f"{len(de['quality_issues'])} issue(s) · {len(de['outliers'])} outlier(s)"
                f"</div>",
                unsafe_allow_html=True,
            )

            st.markdown("---")

            if st.session_state.pm_ready:
                st.markdown("---")
                st.markdown("##### 🧭 Next step: Research Questions")
                st.caption(
                    "The Research Analyst will explore your dataset and propose data paths to investigate. "
                    "Anything on your mind before we dive in?"
                )

                interest_choice = st.radio(
                    "Steer the researcher?",
                    options=["none", "yes"],
                    format_func=lambda x: {
                        "none": "No, nothing on my mind — let the researcher do his job",
                        "yes": "Oh yeah, I'm actually interested in…",
                    }[x],
                    key="user_interest_choice",
                    label_visibility="collapsed",
                )

                if interest_choice == "yes":
                    st.text_area(
                        "What are you curious about?",
                        placeholder=(
                            "e.g. 'I want to know if premium customers churn less' or "
                            "'Does geography affect purchase frequency?'"
                        ),
                        key="user_interest_text",
                        height=90,
                    )

                if st.button("🚀 Generate Research Questions"):
                    user_interest = None
                    if st.session_state.get("user_interest_choice") == "yes":
                        raw_text = st.session_state.get("user_interest_text", "").strip()
                        user_interest = raw_text if raw_text else None

                    add_log(
                        "Research Analyst: Generating research questions...", "system"
                    )
                    if user_interest:
                        add_log(
                            f'Research Analyst: User interest noted — "{user_interest}"',
                            "system",
                        )
                    st.session_state.api_call_count += 1
                    result = run_researcher_agent(
                        metadata=st.session_state.metadata,
                        de_findings=st.session_state.de_findings,
                        user_interest=user_interest,
                    )
                    if "error" in result:
                        add_log(f"Research Analyst Error: {result['detail']}", "error")
                        print(f"[ERROR] Researcher Agent: {result['detail']}")
                        st.error(
                            "⚠️ Research Analyst step failed. Try again or check the activity log."
                        )
                    else:
                        st.session_state.research_paths = result["paths"]
                        pm_result = result.get("primary_metric")
                        st.session_state.primary_metric = pm_result
                        st.session_state.user_interest_path = result.get(
                            "user_interest_path"
                        )
                        add_log(
                            f"Research Analyst: {len(result['paths'])} research questions ready.",
                            "system",
                        )
                        if pm_result:
                            add_log(
                                f"Research Analyst: Primary metric detected — {pm_result['label']} ({pm_result['column']}) at {pm_result['rate_pct']:.1f}%",
                                "system",
                            )
                        else:
                            add_log(
                                "Research Analyst: No primary metric detected (no binary column found).",
                                "system",
                            )
                        if st.session_state.user_interest_path:
                            uip = st.session_state.user_interest_path
                            if uip.get("tool_instructions"):
                                add_log(
                                    f'Research Analyst: User interest path created — "{uip["title"]}"',
                                    "system",
                                )
                            else:
                                add_log(
                                    f'Research Analyst: User interest noted but not feasible with current data — "{uip["title"]}"',
                                    "system",
                                )
                        st.session_state.stage = "RESEARCH"
                        st.rerun()
            else:
                st.warning(
                    "⚠️ Quality score too low to proceed. Review the Quality Report before continuing."
                )

    # ── STAGE: RESEARCH ───────────────────────────────────────────────────
    elif st.session_state.stage == "RESEARCH":
        st.markdown("##### 🔬 STEP 03: SELECT RESEARCH PATHS")

        used_titles = {
            r["path"]["title"] for r in st.session_state.get("analysis_results", [])
        }

        # ── USER INTEREST PATH ────────────────────────────────────────────
        uip = st.session_state.get("user_interest_path")
        if uip:
            has_tools = bool(uip.get("tool_instructions"))
            has_limit = bool(uip.get("limitations_note"))
            if has_tools and not has_limit:
                uip_state = "feasible"
                icon = "🎯"
                title_color = "#00ff9f"
            elif has_tools and has_limit:
                uip_state = "partial"
                icon = "⚡"
                title_color = "#ffcc00"
            else:
                uip_state = "infeasible"
                icon = "🚧"
                title_color = "#ff6b6b"
            uip_already_used = uip["title"] in used_titles

            st.caption("🎯 Your requested path")
            with st.container(border=True):
                if uip_already_used:
                    st.markdown(
                        "<div style='opacity:0.35; filter:blur(1.5px); pointer-events:none;'>",
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    f"<span style='color:{title_color}'><b>{icon} Your question: {uip['title']}</b></span>",
                    unsafe_allow_html=True,
                )
                st.caption(uip["question"])
                if uip_state in ("feasible", "partial"):
                    st.markdown(uip["rationale"])
                    tool_names = " → ".join(t["tool"] for t in uip["tool_instructions"])
                    st.markdown(
                        f"<span style='color:#888; font-size:0.8rem; font-family:monospace'>"
                        f"Tools: {tool_names}</span>",
                        unsafe_allow_html=True,
                    )
                if uip_state == "partial":
                    st.markdown(
                        f"<span style='color:#ffcc00; font-size:0.85rem;'>"
                        f"⚠ Closest approximation — {uip['limitations_note']}</span>",
                        unsafe_allow_html=True,
                    )
                if uip_state == "infeasible":
                    st.markdown(
                        f"<span style='color:#ff6b6b; font-size:0.85rem;'>"
                        f"⚠ {uip['feasibility_note']}</span>",
                        unsafe_allow_html=True,
                    )
                if uip_already_used:
                    st.markdown("</div>", unsafe_allow_html=True)
                if uip_state in ("feasible", "partial"):
                    if st.button(
                        "▶ Analyze This Path",
                        key="path_user_interest",
                        disabled=uip_already_used,
                    ):
                        clean_path = {
                            "title": uip["title"],
                            "question": uip["question"],
                            "tool_instructions": uip["tool_instructions"],
                        }
                        st.session_state.current_path = clean_path
                        add_log(f"Path selected: {clean_path['title']}", "system")
                        st.session_state.api_call_count += 1
                        pm_response = run_pm_gate(
                            current_stage="RESEARCH",
                            metadata=st.session_state.metadata,
                            de_findings=st.session_state.de_findings,
                            selected_path=clean_path,
                            previous_findings=st.session_state.analysis_results or None,
                        )
                        if "error" in pm_response:
                            add_log(
                                f"Product Manager Error: {pm_response['detail']}", "error"
                            )
                            print(f"[ERROR] PM Agent: {pm_response['detail']}")
                            st.error(
                                "⚠️ Product Manager step failed. Try again or check the activity log."
                            )
                        else:
                            add_log(
                                f"Product Manager: {pm_response['summary_for_log']}",
                                "system",
                            )
                            st.session_state.pm_summaries.append(
                                pm_response["user_message"]
                            )
                            st.session_state.stage = "ANALYSIS"
                            st.session_state.report_view = "pm_summary"
                            st.rerun()
                else:
                    st.button(
                        "▶ Analyze This Path", key="path_user_interest", disabled=True
                    )
                    st.caption("No tool path available for this question.")

        # ── PATH SELECTION UI ─────────────────────────────────────────────
        paths = st.session_state.research_paths
        st.caption("Researcher-generated paths")

        for i, path in enumerate(paths):
            already_used = path["title"] in used_titles
            with st.container(border=True):
                if already_used:
                    st.markdown(
                        "<div style='opacity:0.35; filter:blur(1.5px); pointer-events:none;'>",
                        unsafe_allow_html=True,
                    )
                st.markdown(f"**{i + 1}. {path['title']}**")
                st.caption(path["question"])
                tool_names = " → ".join(t["tool"] for t in path["tool_instructions"])
                st.markdown(
                    f"<span style='color:#888; font-size:0.8rem; font-family:monospace'>"
                    f"Tools: {tool_names}</span>",
                    unsafe_allow_html=True,
                )
                if already_used:
                    st.markdown("</div>", unsafe_allow_html=True)
                if st.button(
                    "▶ Analyze This Path", key=f"path_{i}", disabled=already_used
                ):
                    st.session_state.current_path = path
                    add_log(f"Path selected: {path['title']}", "system")

                    # PM gates transition to ANALYSIS
                    st.session_state.api_call_count += 1
                    pm_response = run_pm_gate(
                        current_stage="RESEARCH",
                        metadata=st.session_state.metadata,
                        de_findings=st.session_state.de_findings,
                        selected_path=path,
                        previous_findings=st.session_state.analysis_results or None,
                    )

                    if "error" in pm_response:
                        add_log(
                            f"Product Manager Error: {pm_response['detail']}", "error"
                        )
                        print(f"[ERROR] PM Agent: {pm_response['detail']}")
                        st.error(
                            "⚠️ Product Manager step failed. Try again or check the activity log."
                        )
                    else:
                        add_log(
                            f"Product Manager: {pm_response['summary_for_log']}",
                            "system",
                        )
                        st.session_state.pm_summaries.append(
                            pm_response["user_message"]
                        )
                        st.session_state.stage = "ANALYSIS"
                        st.session_state.report_view = "pm_summary"
                        st.rerun()

        if len(st.session_state.get("analysis_results", [])) >= 1:
            st.markdown("---")
            n = len(st.session_state.analysis_results)
            label = "path" if n == 1 else "paths"
            st.caption(f"You've already analyzed {n} {label}.")
            if st.button(
                "⏭ Skip to Dashboard",
                key="Finish analysis : proceed to dashboard",
            ):
                st.session_state.stage = "DASHBOARD"
                st.rerun()

    # ── STAGE: ANALYSIS ────────────────────────────────────────────────
    elif st.session_state.stage == "ANALYSIS":
        st.markdown("##### 📊 STEP 04: ANALYSIS")
        path = st.session_state.current_path

        if path is None:
            st.error("No research path selected. Go back to Step 03.")
        else:
            st.markdown(f"**Path:** {path['title']}")
            st.caption(path["question"])

            # ── RUN TOOLS + DA AGENT (first visit for this path) ──────────
            if st.session_state.da_findings is None:
                if st.button("⚡ Run Analysis"):
                    df = st.session_state.raw_data
                    tool_results = []
                    all_ok = True

                    # Sequential Switchboard execution
                    for instruction in path["tool_instructions"]:
                        tool_name = instruction["tool"]
                        add_log(f"Running tool: {tool_name}...", "system")
                        result = run_tool(instruction, df)

                        if "error" in result:
                            add_log(
                                f"Tool error [{tool_name}]: {result['detail']}", "error"
                            )
                            print(f"[ERROR] Tool {tool_name}: {result['detail']}")
                            st.error(
                                f"⚠️ Tool '{tool_name}' failed. Try again or check the activity log."
                            )
                            all_ok = False
                            break

                        add_log(f"Tool complete: {tool_name}.", "system")
                        tool_results.append(result)

                    if all_ok and tool_results:
                        st.session_state.tool_result = tool_results

                        # Data Analyst interprets all results
                        add_log("Data Analyst: Interpreting results...", "system")
                        st.session_state.api_call_count += 1
                        column_skewness = {
                            col: stats["skewness"]
                            for col, stats in st.session_state.metadata.get("numeric_summary", {}).items()
                            if "skewness" in stats
                        }
                        da_response = run_da_agent(
                            path,
                            tool_results,
                            cross_path_summary=st.session_state.cross_path_summary,
                            column_skewness=column_skewness,
                        )

                        if "error" in da_response:
                            add_log(
                                f"Data Analyst Error: {da_response['detail']}", "error"
                            )
                            print(f"[ERROR] DA Agent: {da_response['detail']}")
                            st.error(
                                "⚠️ Data Analyst step failed. Try again or check the activity log."
                            )
                        else:
                            st.session_state.da_findings = da_response
                            add_log("Data Analyst: Analysis complete.", "system")

                            # Accumulate in analysis_results
                            st.session_state.analysis_results.append(
                                {
                                    "path": path,
                                    "tool_result": tool_results,
                                    "da_findings": da_response,
                                }
                            )

                            # Build cross-path summary for next path's DA call
                            st.session_state.cross_path_summary = (
                                build_cross_path_summary(
                                    st.session_state.analysis_results,
                                    st.session_state.metadata,
                                )
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
                    f"Recommended chart: {da['recommended_viz']} — {da['viz_rationale']}</span>",
                    unsafe_allow_html=True,
                )

                st.markdown("---")
                if len(st.session_state.analysis_results) < 3:
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("🔄 Analyze Another Path"):
                            # Reset path-level state, return to RESEARCH
                            st.session_state.current_path = None
                            st.session_state.da_findings = None
                            st.session_state.tool_result = None
                            st.session_state.stage = "RESEARCH"
                            st.rerun()
                    with col_b:
                        if st.button("📈 View Final Dashboard"):
                            st.session_state.stage = "DASHBOARD"
                            st.rerun()
                else:
                    st.warning(
                        "⚠️ You've reached the 3-path limit. Proceed to the dashboard for final synthesis."
                    )
                    if st.button("📈 View Final Dashboard"):
                        st.session_state.stage = "DASHBOARD"
                        st.rerun()

    # ── STAGE: DASHBOARD ───────────────────────────────────────────────
    elif st.session_state.stage == "DASHBOARD":
        st.markdown("##### 📈 STEP 05: DASHBOARD")

        # ── PHASE A: PM FINAL SYNTHESIS ───────────────────────────────
        if st.session_state.pm_final_summary is None:
            with st.spinner("Product Manager synthesizing findings..."):
                st.session_state.api_call_count += 1
                pm_response = run_pm_gate(
                    current_stage="DASHBOARD",
                    metadata=st.session_state.metadata,
                    de_findings=st.session_state.de_findings,
                    previous_findings=st.session_state.analysis_results,
                )
            if "error" in pm_response:
                add_log(f"Product Manager Error: {pm_response['detail']}", "error")
                print(f"[ERROR] PM Agent: {pm_response['detail']}")
                st.error(
                    "⚠️ Product Manager step failed. Try again or check the activity log."
                )
            else:
                st.session_state.pm_final_summary = pm_response["user_message"]
                st.session_state.pm_summaries.append(pm_response["user_message"])
                add_log(f"Product Manager: {pm_response['summary_for_log']}", "system")
                st.rerun()

        # ── PHASE B: BI AGENT ─────────────────────────────────────────
        elif st.session_state.chart_configs is None:
            with st.spinner("BI Developer building your dashboard..."):
                st.session_state.api_call_count += 1
                bi_response = run_bi_agent(
                    st.session_state.analysis_results,
                    st.session_state.pm_final_summary,
                )
            if "error" in bi_response:
                add_log(f"BI Developer Error: {bi_response['detail']}", "error")
                print(f"[ERROR] BI Agent: {bi_response['detail']}")
                st.error(
                    "⚠️ BI Developer step failed. Try again or check the activity log."
                )
            else:
                st.session_state.chart_configs = bi_response
                add_log("BI Developer: Dashboard config ready.", "system")
                st.rerun()

        # ── PHASE D: SYNTHESIS AGENT ──────────────────────────────────
        elif st.session_state.synthesis is None:
            with st.spinner("Strategy Analyst generating recommendations..."):
                st.session_state.api_call_count += 1
                syn_response = run_synthesis_agent(
                    st.session_state.analysis_results,
                    st.session_state.chart_configs,
                    cross_path_summary=st.session_state.cross_path_summary,
                )
            if "error" in syn_response:
                add_log(f"Strategy Analyst Error: {syn_response['detail']}", "error")
                print(f"[ERROR] Synthesis Agent: {syn_response['detail']}")
                st.error(
                    "⚠️ Strategy Analyst step failed. Try again or check the activity log."
                )
            else:
                st.session_state.synthesis = syn_response
                add_log("Strategy Analyst: Recommendations ready.", "system")
                st.rerun()

        # ── PHASE E: RENDER DASHBOARD ─────────────────────────────────
        else:
            cfg = st.session_state.chart_configs

            with st.expander("🔍 DEBUG: BI Agent raw output", expanded=True):
                st.json(cfg)

            st.info(cfg["dashboard_narrative"])

            # KPI row
            kpis = cfg["kpis"]
            kpi_cols = st.columns(len(kpis))
            for col, kpi in zip(kpi_cols, kpis):
                delta_sym = (
                    "↑"
                    if kpi["delta"] == "up"
                    else "↓"
                    if kpi["delta"] == "down"
                    else "~"
                )
                with col:
                    st.metric(label=kpi["label"], value=kpi["value"], delta=delta_sym)
                    st.caption(kpi["context"])

            st.markdown("---")

            # Charts
            for chart in cfg["charts"]:
                chart_type = chart["chart_type"]
                if chart_type == "bar":
                    trace = go.Bar(x=chart["x"], y=chart["y"])
                elif chart_type == "line":
                    trace = go.Scatter(x=chart["x"], y=chart["y"], mode="lines")
                elif chart_type == "scatter":
                    trace = go.Scatter(x=chart["x"], y=chart["y"], mode="markers")
                else:  # heatmap
                    trace = go.Heatmap(z=[chart["y"]])

                fig = go.Figure(data=[trace])
                fig.update_layout(
                    title=chart["title"],
                    xaxis_title=chart["x_label"],
                    yaxis_title=chart["y_label"],
                    paper_bgcolor="#050505",
                    plot_bgcolor="#0a0a0a",
                    font_color="#00ff9f",
                )
                st.plotly_chart(fig, use_container_width=True)
                st.caption(f"Source: {chart['source_path']}")
                if chart.get("explanation"):
                    st.markdown(f"*{chart['explanation']}*")

            # Recommendations
            st.markdown("---")
            st.markdown("#### Key Recommendations")
            for rec in st.session_state.synthesis["recommendations"]:
                st.markdown(f"- {rec}")

            # Download report
            st.markdown("---")
            html_bytes = build_html_report(
                st.session_state.pm_final_summary,
                st.session_state.chart_configs,
                st.session_state.synthesis,
                st.session_state.metadata,
                st.session_state.de_findings,
                st.session_state.analysis_results,
            ).encode("utf-8")
            st.download_button(
                label="⬇ Download Full Report",
                data=html_bytes,
                file_name="dig_report.html",
                mime="text/html",
            )

# --- COLUMN 3: LIVING REPORT ---
with col_report:
    st.markdown("### 📑 LIVING REPORT")

    # ── TAB TOGGLE BUTTONS ─────────────────────────────────────────────
    tab_cols = st.columns(5)

    with tab_cols[0]:
        if st.button("📋 METADATA", disabled=st.session_state.metadata is None):
            st.session_state.report_view = "metadata"
            st.rerun()

    with tab_cols[1]:
        if st.button(
            "🔧 Quality Report", disabled=st.session_state.de_findings is None
        ):
            st.session_state.report_view = "de_report"
            st.rerun()

    with tab_cols[2]:
        if st.button(
            "💬 Pipeline Summary", disabled=len(st.session_state.pm_summaries) == 0
        ):
            st.session_state.report_view = "pm_summary"
            st.rerun()

    with tab_cols[3]:
        if st.button(
            "📊 Analysis Findings", disabled=len(st.session_state.analysis_results) == 0
        ):
            st.session_state.report_view = "da_findings"
            st.rerun()

    with tab_cols[4]:
        if st.button(
            "💬 Activity Log", disabled=len(st.session_state.pm_summaries) == 0
        ):
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
        label="⬇ Download as Markdown",
        data=content_md,
        file_name=f"DIG_{view_label}_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
        mime="text/markdown",
    )

# ==========================================
# 7. FOOTER / SYSTEM STATUS
# ==========================================
st.divider()
status_cols = st.columns(5)
status_cols[0].caption(f"STAGE: {st.session_state.stage}")
status_cols[1].caption(f"VIEW: {st.session_state.report_view}")
status_cols[2].caption(
    f"ROWS: {len(st.session_state.raw_data) if st.session_state.raw_data is not None else 0}"
)
status_cols[3].caption("MODEL: CLAUDE-HAIKU-4")
status_cols[4].caption(f"COST: ${st.session_state.estimated_cost_usd:.4f}")
