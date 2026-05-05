import plotly.graph_objects as go

# ══════════════════════════════════════════════════════════════════════
# VIZ KIT
# Converts BI agent chart specs into Plotly traces using raw tool results.
# The BI agent references which tool result to render; this module
# extracts the actual data and builds the trace — no LLM data involved.
# ══════════════════════════════════════════════════════════════════════

CYAN = "#00ff9f"


def _find_tool_result(tool_results: list, source_tool: str, source_col: str | None) -> dict | None:
    for tr in tool_results:
        if tr.get("tool") != source_tool:
            continue
        if source_col is None:
            return tr
        if (
            tr.get("col") == source_col
            or tr.get("col1") == source_col
            or tr.get("group_col") == source_col
            or tr.get("date_col") == source_col
            or tr.get("value_col") == source_col
        ):
            return tr
    return None


def extract_trace(chart_spec: dict, analysis_results: list):
    """
    Build a Plotly trace from a reference-based BI chart spec.

    chart_spec keys used:
      source_path_index  — index into analysis_results
      source_tool        — starter kit tool name
      source_col         — column to match (None = aggregate all runs)
      chart_type         — 'bar' | 'line' | 'heatmap'
    """
    idx = chart_spec.get("source_path_index", 0)
    source_tool = chart_spec["source_tool"]
    source_col = chart_spec.get("source_col")
    chart_type = chart_spec["chart_type"]

    if idx >= len(analysis_results):
        return go.Bar(x=[], y=[])

    tool_results = analysis_results[idx].get("tool_result", [])

    # anomaly_detection with no column → aggregate total_flagged per column
    if source_tool == "anomaly_detection" and source_col is None:
        runs = [t for t in tool_results if t.get("tool") == "anomaly_detection"]
        x = [t["col"] for t in runs]
        y = [t["total_flagged"] for t in runs]
        return go.Bar(x=x, y=y, marker_color=CYAN)

    tr = _find_tool_result(tool_results, source_tool, source_col)
    if tr is None:
        return go.Bar(x=[], y=[])

    if source_tool == "distribution_analysis":
        bins = tr["histogram_bins"]
        x = [f"{b['bin_start']:.0f}–{b['bin_end']:.0f}" for b in bins]
        y = [b["count"] for b in bins]
        return go.Bar(x=x, y=y, marker_color=CYAN)

    if source_tool == "top_n_values":
        x = [v["value"] for v in tr["values"]]
        y = [v["count"] for v in tr["values"]]
        return go.Bar(x=x, y=y, marker_color=CYAN)

    if source_tool == "segment_comparison":
        x = [s["segment"] for s in tr["segments"]]
        y = [s["mean"] for s in tr["segments"]]
        if chart_type == "line":
            return go.Scatter(x=x, y=y, mode="lines", line=dict(color=CYAN, width=2))
        return go.Bar(x=x, y=y, marker_color=CYAN)

    if source_tool == "time_series_trend":
        x = [d["period"] for d in tr["monthly_data"]]
        y = [d["value"] for d in tr["monthly_data"]]
        return go.Scatter(x=x, y=y, mode="lines", line=dict(color=CYAN, width=2))

    if source_tool == "rolling_average":
        x = [d["date"] for d in tr["data"]]
        y = [d["rolling_avg"] for d in tr["data"]]
        return go.Scatter(x=x, y=y, mode="lines", line=dict(color=CYAN, width=2))

    if source_tool == "anomaly_detection":
        x = [str(a["value"]) for a in tr["anomalies"]]
        y = [1] * len(tr["anomalies"])
        return go.Bar(x=x, y=y, marker_color=CYAN)

    if source_tool == "funnel_analysis":
        x = [s["stage"] for s in tr["stages"]]
        y = [s["count"] for s in tr["stages"]]
        return go.Bar(x=x, y=y, marker_color=CYAN)

    if source_tool == "correlation_matrix":
        pairs = tr["top_pairs"]
        x = [f"{p['col_a']} × {p['col_b']}" for p in pairs]
        y = [abs(p["correlation"]) for p in pairs]
        return go.Bar(x=x, y=y, marker_color=CYAN)

    if source_tool == "cross_tab":
        x = [r["row_label"] for r in tr["rows"]]
        y = [sum(r["counts"].values()) for r in tr["rows"]]
        return go.Bar(x=x, y=y, marker_color=CYAN)

    if source_tool == "cohort_retention":
        cohorts = tr["cohorts"]
        periods = sorted({p for v in tr["retention_pct"].values() for p in v})
        z = [[tr["retention_pct"].get(c, {}).get(p, 0) for p in periods] for c in cohorts]
        return go.Heatmap(z=z, x=periods, y=cohorts, colorscale="Viridis")

    return go.Bar(x=[], y=[])
