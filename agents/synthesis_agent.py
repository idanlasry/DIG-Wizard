# synthesis_agent.py
import json
from anthropic import Anthropic
from pydantic import BaseModel, ValidationError, field_validator
import streamlit as st
from utils.utils import calculate_cost

client = Anthropic()

# ══════════════════════════════════════════════════════════════════════
# BLOCK 1 — SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════

SYNTHESIS_SYSTEM_PROMPT = """
You are a senior strategy consultant. You receive completed analysis paths with DA findings,
and a BI summary with KPIs and chart explanations.

Write a 3-4 sentence executive narrative synthesizing the most important cross-path insight —
what the data reveals as a whole, not just per-path summaries.

Then return 2-4 concrete business recommendations. Each recommendation must be:
- Actionable (a decision or action a business can take)
- Specific to the actual data provided (no generic advice)
- Written in plain executive language

Respond with ONLY a valid JSON object. No markdown. No explanation. No code blocks.

Use exactly this structure:
{
  "narrative": "<3-4 sentence executive synthesis>",
  "recommendations": ["<action 1>", "<action 2>", "<action 3>"]
}
"""

# ══════════════════════════════════════════════════════════════════════
# BLOCK 2 — PYDANTIC VALIDATION MODELS
# ══════════════════════════════════════════════════════════════════════


class SynthesisOutput(BaseModel):
    narrative: str
    recommendations: list[str]

    @field_validator("recommendations")
    @classmethod
    def must_have_two_to_four(cls, v):
        if not (2 <= len(v) <= 4):
            raise ValueError(f"recommendations must have 2-4 items, got {len(v)}")
        return v


# ══════════════════════════════════════════════════════════════════════
# BLOCK 3 — CONTEXT BUILDER + API CALL
# ══════════════════════════════════════════════════════════════════════


def build_synthesis_context(
    analysis_results: list[dict],
    bi_findings: dict,
    cross_path_summary: dict | None = None,
) -> str:
    parts = []

    if cross_path_summary:
        parts.append("CROSS-PATH SIGNALS (pre-computed, Python — no LLM):")

        cited = cross_path_summary.get("most_cited_columns", {})
        if cited:
            col_str = ", ".join(f"{c} ({cnt}x)" for c, cnt in cited.items())
            parts.append(f"- Most-cited columns: {col_str}")

        shared_labels = cross_path_summary.get("shared_stat_labels", [])
        if shared_labels:
            parts.append(f"- Consistent stat labels across paths: {', '.join(shared_labels)}")

        overlaps = cross_path_summary.get("potential_overlaps", [])
        if overlaps:
            parts.append("- Potential contradictions / confirmations to resolve:")
            for ov in overlaps:
                entries_str = "; ".join(
                    f'{e["path"]}: {e["value"]}' for e in ov["occurrences"]
                )
                parts.append(f'  • "{ov["label"]}": {entries_str}')

        parts.append("")

    parts.append(f"COMPLETED ANALYSIS PATHS: {len(analysis_results)}")

    for i, result in enumerate(analysis_results, 1):
        path = result.get("path", {})
        da = result.get("da_findings", {})
        parts.append(f"\n--- Path {i}: {path.get('title', '?')} ---")
        parts.append(f"Question: {path.get('question', '?')}")
        parts.append(f"Headline: {da.get('headline', '?')}")
        parts.append(f"Key insights: {json.dumps(da.get('key_insights', []))}")
        parts.append(f"Supporting stats: {json.dumps(da.get('supporting_stats', []))}")

    parts.append("\nBI DASHBOARD SUMMARY:")
    parts.append(f"Narrative: {bi_findings.get('dashboard_narrative', '?')}")

    kpis = bi_findings.get("kpis", [])
    if kpis:
        parts.append("KPIs:")
        for kpi in kpis:
            parts.append(
                f"  - {kpi.get('label', '?')}: {kpi.get('value', '?')} ({kpi.get('context', '')})"
            )

    charts = bi_findings.get("charts", [])
    if charts:
        parts.append("Charts:")
        for chart in charts:
            explanation = chart.get("explanation", "")
            parts.append(f"  - {chart.get('title', '?')}: {explanation}")

    parts.append("\nBased on the above, generate your synthesis JSON.")
    return "\n".join(parts)


def call_synthesis_agent(
    analysis_results: list[dict],
    bi_findings: dict,
    cross_path_summary: dict | None = None,
) -> dict:
    context = build_synthesis_context(analysis_results, bi_findings, cross_path_summary)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=SYNTHESIS_SYSTEM_PROMPT,
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
        raise ValueError(
            f"Synthesis Agent returned invalid JSON: {e}\nRaw output: {raw_text}"
        )


# ══════════════════════════════════════════════════════════════════════
# BLOCK 4 — GATE RUNNER
# Called from app.py. Never raises — returns error dict on failure.
# ══════════════════════════════════════════════════════════════════════


def run_synthesis_agent(
    analysis_results: list[dict],
    bi_findings: dict,
    cross_path_summary: dict | None = None,
) -> dict:
    try:
        raw = call_synthesis_agent(analysis_results, bi_findings, cross_path_summary)
        output = SynthesisOutput(**raw)
        return output.model_dump()
    except ValidationError as e:
        return {"error": "validation_failed", "detail": str(e)}
    except ValueError as e:
        return {"error": "invalid_json", "detail": str(e)}
    except Exception as e:
        return {"error": "api_failure", "detail": str(e)}
