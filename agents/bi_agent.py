# bi_agent.py
import json
from anthropic import Anthropic
from pydantic import BaseModel, ValidationError, field_validator

client = Anthropic()

# ══════════════════════════════════════════════════════════════════════
# BLOCK 1 — SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════

BI_SYSTEM_PROMPT = """
You are a senior BI developer building an executive dashboard from completed data analysis results.

You receive:
- A PM executive synthesis summarizing cross-path findings
- A list of research paths that have already been analyzed, each with DA findings

Your job: decide what to show on the dashboard. Choose the most meaningful KPIs and charts
that tell a coherent story across all completed paths.

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
      "chart_type": "<'bar' | 'line' | 'scatter' | 'heatmap'>",
      "title": "<chart title>",
      "x_label": "<x axis label>",
      "y_label": "<y axis label>",
      "x": ["<value1>", "<value2>"],
      "y": [<number1>, <number2>],
      "source_path": "<title of the research path this data came from>",
      "explanation": "<1-2 sentence plain-language explanation for a non-technical executive>"
    }
  ],
  "dashboard_narrative": "<2-3 sentence executive summary across all paths>"
}

Rules:
- kpis must have 3-6 items.
- charts must have 2-4 items.
- Order kpis by impact: most important KPI first.
- Order charts by strength of finding: strongest insight first.
- Only use values that exist in the da_findings supporting_stats or key_insights you received.
- Never invent numbers.
- x and y arrays must have the same length.
- y values must be numbers (int or float), not strings.
- chart_type must be exactly one of: bar, line, scatter, heatmap.
- Write each chart explanation in plain stakeholder language, as if presenting to a non-technical executive who has never seen this data.
- Never add fields outside this schema.
- Never return text outside the JSON object.
"""

# ══════════════════════════════════════════════════════════════════════
# BLOCK 2 — PYDANTIC VALIDATION MODELS
# ══════════════════════════════════════════════════════════════════════


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
    x: list
    y: list
    source_path: str
    explanation: str

    @field_validator("chart_type")
    @classmethod
    def chart_type_must_be_valid(cls, v):
        if v not in {"bar", "line", "scatter", "heatmap"}:
            raise ValueError(f"chart_type must be bar/line/scatter/heatmap, got '{v}'")
        return v

    @field_validator("y")
    @classmethod
    def y_must_match_x(cls, v, info):
        x = info.data.get("x", [])
        if len(v) != len(x):
            raise ValueError(
                f"x and y arrays must have same length. x={len(x)}, y={len(v)}"
            )
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

    for i, result in enumerate(analysis_results, 1):
        path = result.get("path", {})
        da = result.get("da_findings", {})
        parts.append(f"\n--- Path {i}: {path.get('title', '?')} ---")
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
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        system=BI_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
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
