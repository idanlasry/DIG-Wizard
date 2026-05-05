# bi_agent.py
import json
from anthropic import Anthropic
from pydantic import BaseModel, ValidationError, field_validator
import streamlit as st
from utils.utils import with_backoff, calculate_cost

client = Anthropic()

# ══════════════════════════════════════════════════════════════════════
# BLOCK 1 — SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════

BI_SYSTEM_PROMPT = """
You are a senior BI developer selecting and ordering charts for an executive dashboard.

You receive:
- A PM executive synthesis summarizing cross-path findings
- A list of completed research paths, each with the exact tools that ran and DA findings

Your job: choose the most impactful KPIs and select which tool results to visualize.
You do NOT provide chart data — the renderer pulls real data from the tool outputs.
You only specify WHAT to show and HOW to show it.

Respond with ONLY a valid JSON object. No explanation, no markdown, no code blocks.

Use exactly this structure:

{
  "kpis": [
    {
      "label": "<short metric name>",
      "value": "<the number or percentage as a string>",
      "delta": "<'up' | 'down' | 'neutral'>",
      "context": "<one sentence — what this KPI means>"
    }
  ],
  "charts": [
    {
      "chart_type": "<'bar' | 'line' | 'heatmap'>",
      "title": "<chart title>",
      "x_label": "<x axis label>",
      "y_label": "<y axis label>",
      "source_path_index": <0-based integer — index of the path in COMPLETED PATHS>,
      "source_tool": "<exact tool name from that path's tool list>",
      "source_col": "<column name to use, or null if not needed>",
      "source_path": "<title of the research path>",
      "explanation": "<1-2 sentence plain-language explanation for a non-technical executive>"
    }
  ],
  "dashboard_narrative": "<2-3 sentence executive summary across all paths>"
}

Rules:
- kpis must have 3-6 items. Pull KPI values only from DA supporting_stats — never invent numbers.
- charts must have 2-4 items.
- Order kpis by impact: most important KPI first.
- Order charts by strength of finding: strongest insight first.
- source_tool must exactly match a tool name listed under that path's "Tools run" section.
- source_col identifies which specific tool run to render when a tool was called more than once:
  - segment_comparison: set source_col to the group_col (the segmenting column, e.g. "NumOfProducts"),
    NOT the value_col. Two segment_comparison runs with different group_cols must have different source_cols.
  - cross_tab: set source_col to col1.
  - time_series_trend / rolling_average: set source_col to date_col.
  - distribution_analysis / top_n_values / anomaly_detection: set source_col to col.
  - correlation_matrix / funnel_analysis / cohort_retention: set source_col=null (only one run per path).
- For anomaly_detection: set source_col=null to get a bar of total_flagged counts per column,
  or set source_col="<col>" to get individual anomaly values for that column.
- chart_type must be exactly one of: bar, line, heatmap.
- Never use scatter — data is aggregated; individual paired observations are not available.
- Never add fields outside this schema.
- Never return text outside the JSON object.

Tool → best chart type guide:
- distribution_analysis → bar (histogram of a column's distribution)
- top_n_values → bar (most frequent values)
- segment_comparison → bar or line (metric mean per segment, ordered by value)
- time_series_trend → line (trend over time periods)
- rolling_average → line (smoothed metric over dates)
- anomaly_detection → bar (source_col=null: flagged count per column; source_col=X: anomaly values)
- funnel_analysis → bar (stage counts or conversion rates)
- correlation_matrix → bar (top correlated pairs by absolute strength)
- cross_tab → bar (row counts per category)
- cohort_retention → heatmap (retention matrix)
"""

# ══════════════════════════════════════════════════════════════════════
# BLOCK 2 — PYDANTIC VALIDATION MODELS
# ══════════════════════════════════════════════════════════════════════

KNOWN_TOOLS = {
    "distribution_analysis", "top_n_values", "segment_comparison",
    "time_series_trend", "rolling_average", "anomaly_detection",
    "funnel_analysis", "correlation_matrix", "cross_tab", "cohort_retention",
}


class KPIBlock(BaseModel):
    label: str
    value: str
    delta: str
    context: str

    @field_validator("delta")
    @classmethod
    def delta_must_be_valid(cls, v):
        if v not in {"up", "down", "neutral"}:
            raise ValueError(f"delta must be 'up', 'down', or 'neutral', got '{v}'")
        return v


class ChartConfig(BaseModel):
    chart_type: str
    title: str
    x_label: str
    y_label: str
    source_path_index: int
    source_tool: str
    source_col: str | None = None
    source_path: str
    explanation: str

    @field_validator("chart_type")
    @classmethod
    def chart_type_must_be_valid(cls, v):
        if v not in {"bar", "line", "heatmap"}:
            raise ValueError(f"chart_type must be bar/line/heatmap, got '{v}'")
        return v

    @field_validator("source_tool")
    @classmethod
    def source_tool_must_be_valid(cls, v):
        if v not in KNOWN_TOOLS:
            raise ValueError(f"source_tool must be one of {sorted(KNOWN_TOOLS)}, got '{v}'")
        return v


class BIFindings(BaseModel):
    kpis: list[KPIBlock]
    charts: list[ChartConfig]
    dashboard_narrative: str

    @field_validator("kpis")
    @classmethod
    def must_have_three_to_six_kpis(cls, v):
        if not (3 <= len(v) <= 6):
            raise ValueError(f"kpis must have 3-6 items, got {len(v)}")
        return v

    @field_validator("charts")
    @classmethod
    def must_have_two_to_four_charts(cls, v):
        if not (2 <= len(v) <= 4):
            raise ValueError(f"charts must have 2-4 items, got {len(v)}")
        return v


# ══════════════════════════════════════════════════════════════════════
# BLOCK 3 — CONTEXT BUILDER + API CALL
# ══════════════════════════════════════════════════════════════════════


def build_bi_context(analysis_results: list[dict], pm_summary: str) -> str:
    parts = []
    parts.append("PM EXECUTIVE SYNTHESIS:")
    parts.append(pm_summary)
    parts.append("")
    parts.append(f"COMPLETED PATHS: {len(analysis_results)}")

    for i, result in enumerate(analysis_results):
        path = result.get("path", {})
        da = result.get("da_findings", {})
        tool_results = result.get("tool_result", [])

        parts.append(f"\n--- Path {i}: {path.get('title', '?')} ---")
        parts.append(f"Path index: {i}")

        # List the exact tools that ran so the LLM can reference them
        if tool_results:
            parts.append("Tools run:")
            for tr in tool_results:
                tool_name = tr.get("tool", "?")
                if tool_name == "segment_comparison":
                    parts.append(
                        f"  {tool_name}(group_col=\"{tr.get('group_col','?')}\", value_col=\"{tr.get('value_col','?')}\")"
                    )
                elif tool_name == "cross_tab":
                    parts.append(
                        f"  {tool_name}(col1=\"{tr.get('col1','?')}\", col2=\"{tr.get('col2','?')}\")"
                    )
                elif tool_name in ("time_series_trend", "rolling_average"):
                    parts.append(
                        f"  {tool_name}(date_col=\"{tr.get('date_col','?')}\", value_col=\"{tr.get('value_col','?')}\")"
                    )
                else:
                    col = tr.get("col") or tr.get("value_col")
                    if col:
                        parts.append(f"  {tool_name}(col=\"{col}\")")
                    else:
                        parts.append(f"  {tool_name}()")

        parts.append(f"Question: {path.get('question', '?')}")
        parts.append(f"Headline: {da.get('headline', '?')}")
        parts.append(f"Insights: {json.dumps(da.get('key_insights', []))}")
        parts.append(f"Supporting stats: {json.dumps(da.get('supporting_stats', []))}")
        parts.append(f"Recommended viz: {da.get('recommended_viz', '?')}")
        if da.get("caveats"):
            parts.append(f"Caveats: {da['caveats']}")

    parts.append("\nBased on the above, generate your BI dashboard JSON.")
    return "\n".join(parts)


def call_bi_agent(analysis_results: list[dict], pm_summary: str) -> dict:
    context = build_bi_context(analysis_results, pm_summary)
    response = with_backoff(
        client.messages.create,
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        system=BI_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
    )
    st.session_state.total_input_tokens += response.usage.input_tokens
    st.session_state.total_output_tokens += response.usage.output_tokens
    st.session_state.estimated_cost_usd += calculate_cost(
        response.usage.input_tokens,
        response.usage.output_tokens,
        model="claude-haiku-4-5-20251001",
    )
    raw_text = (
        response.content[0]
        .text.strip()
        .removeprefix("```json")
        .removesuffix("```")
        .strip()
    )
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"BI Agent returned invalid JSON: {e}\nRaw output: {raw_text}")


# ══════════════════════════════════════════════════════════════════════
# BLOCK 4 — GATE RUNNER
# Called from app.py. Never raises — returns error dict on failure.
# ══════════════════════════════════════════════════════════════════════


def run_bi_agent(analysis_results: list[dict], pm_summary: str) -> dict:
    try:
        raw = call_bi_agent(analysis_results, pm_summary)
        findings = BIFindings(**raw)
        return findings.model_dump()
    except ValidationError as e:
        return {"error": "validation_failed", "detail": str(e)}
    except ValueError as e:
        return {"error": "invalid_json", "detail": str(e)}
    except Exception as e:
        return {"error": "api_failure", "detail": str(e)}
