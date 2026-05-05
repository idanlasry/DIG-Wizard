# da_agent.py
import json
from anthropic import Anthropic
from pydantic import BaseModel, ValidationError, field_validator
import streamlit as st
from utils.utils import with_backoff, calculate_cost

client = Anthropic()

# ══════════════════════════════════════════════════════════════════════
# BLOCK 1 — SYSTEM PROMPT
# DA Agent identity and output rules.
# Stateless — receives path context + all tool results on every call.
# Never does math. Only interprets what pandas returned.
# ══════════════════════════════════════════════════════════════════════

DA_SYSTEM_PROMPT = """
You are a senior data analyst interpreting the output of automated pandas analysis tools.

You receive:
- A research path (title + business question)
- One or more tool results from hardcoded pandas functions

Your job: interpret what the numbers mean for the business. Do not restate the numbers — explain what they imply.

Respond with ONLY a valid JSON object. No explanation, no markdown, no code blocks.

Use exactly this structure:

{
  "headline": "<one punchy sentence summarizing the key finding>",
  "key_insights": [
    "<insight 1 — a business implication, not a number restatement>",
    "<insight 2>",
    "<insight 3>"
  ],
  "supporting_stats": [
    {
      "label": "<what this stat is>",
      "value": "<the number or value>",
      "context": "<what it means>"
    }
  ],
  "recommended_viz": "<one of: bar_chart, line_chart, scatter_plot, heatmap, histogram, funnel_chart, table>",
  "viz_rationale": "<one sentence — why this viz type fits the data>",
  "caveats": "<any limitations, data quality warnings, or follow-up questions — or null if none>"
}

Rules:
- key_insights must have exactly 3 items.
- supporting_stats should have 2–5 items drawn directly from the tool results.
- recommended_viz must be exactly one of the allowed values.
- caveats is a string or null — never an array.
- Never invent numbers not present in the tool results.
- Never add fields outside this schema.
- Never return text outside the JSON object.
- A COLUMN_SKEWNESS section may appear in your context mapping column names to skewness values.
  When interpreting a column whose |skewness| > 1, prefer reporting p50/p75/p95 over the mean.
- When a column in the analysis has |skewness| > 1, note in `caveats` that the distribution is
  highly skewed and the mean overstates or understates the typical value. If caveats would be
  null, set it to this note instead.
"""

# ══════════════════════════════════════════════════════════════════════
# BLOCK 2 — PYDANTIC VALIDATION MODELS
# ══════════════════════════════════════════════════════════════════════

VALID_VIZ_TYPES = {
    "bar_chart",
    "line_chart",
    "scatter_plot",
    "heatmap",
    "histogram",
    "funnel_chart",
    "table",
}


class SupportingStat(BaseModel):
    label: str
    value: str
    context: str


class DAFindings(BaseModel):
    headline: str
    key_insights: list[str]
    supporting_stats: list[SupportingStat]
    recommended_viz: str
    viz_rationale: str
    caveats: str | None

    @field_validator("key_insights")
    @classmethod
    def must_have_three_insights(cls, v):
        if len(v) != 3:
            raise ValueError(f"key_insights must have exactly 3 items, got {len(v)}")
        return v

    @field_validator("supporting_stats")
    @classmethod
    def must_have_two_to_five_stats(cls, v):
        if not (2 <= len(v) <= 5):
            raise ValueError(f"supporting_stats must have 2–5 items, got {len(v)}")
        return v

    @field_validator("recommended_viz")
    @classmethod
    def viz_must_be_valid(cls, v):
        if v not in VALID_VIZ_TYPES:
            raise ValueError(
                f"'{v}' is not a valid viz type. Must be one of: {sorted(VALID_VIZ_TYPES)}"
            )
        return v


# ══════════════════════════════════════════════════════════════════════
# BLOCK 3 — CONTEXT BUILDER
# Packages the research path + all tool results into one prompt string.
# ══════════════════════════════════════════════════════════════════════


_MAX_RESULT_CHARS = 8_000  # per tool result; keeps total prompt well under 200k tokens


def _truncate_result(result: dict) -> str:
    serialized = json.dumps(result, indent=2)
    if len(serialized) <= _MAX_RESULT_CHARS:
        return serialized
    return serialized[:_MAX_RESULT_CHARS] + f"\n... [truncated — {len(serialized) - _MAX_RESULT_CHARS} chars omitted]"


def build_da_context(
    current_path: dict,
    tool_results: list[dict],
    cross_path_summary: dict | None = None,
    column_skewness: dict | None = None,
) -> str:
    """
    Builds the user-turn message for the DA Agent.
    Includes: research question, optional prior-path signals, tool results.
    """
    parts = []

    parts.append(f"RESEARCH PATH: {current_path.get('title', '?')}")
    parts.append(f"BUSINESS QUESTION: {current_path.get('question', '?')}")

    if cross_path_summary:
        n = cross_path_summary.get("paths_completed", 0)
        parts.append(f"\nPRIOR PATH SIGNALS ({n} path(s) completed before this one):")

        cited = cross_path_summary.get("most_cited_columns", {})
        if cited:
            col_str = ", ".join(f"{c} ({cnt}x)" for c, cnt in cited.items())
            parts.append(f"- Most-cited columns across prior paths: {col_str}")

        shared_labels = cross_path_summary.get("shared_stat_labels", [])
        if shared_labels:
            parts.append(f"- Stat labels seen in multiple paths: {', '.join(shared_labels)}")

        headlines = cross_path_summary.get("headlines", [])
        if headlines:
            parts.append("- Prior path headlines:")
            for h in headlines:
                parts.append(f'  • "{h["path"]}": {h["headline"]}')

    parts.append("")
    parts.append(f"TOOL RESULTS ({len(tool_results)} total):")

    for i, result in enumerate(tool_results, 1):
        tool_name = result.get("tool", f"tool_{i}")
        parts.append(f"\n--- Tool {i}: {tool_name} ---")
        parts.append(_truncate_result(result))

    if column_skewness:
        skew_lines = [f"  {col}: {round(val, 3)}" for col, val in column_skewness.items()]
        parts.append(
            "COLUMN_SKEWNESS (use |value| > 1 as threshold for highly skewed):\n"
            + "\n".join(skew_lines)
        )

    parts.append("\nBased on the above, generate your DA findings JSON.")

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════
# BLOCK 4 — THE DA CALL
# ══════════════════════════════════════════════════════════════════════


def call_da_agent(
    current_path: dict,
    tool_results: list[dict],
    cross_path_summary: dict | None = None,
    column_skewness: dict | None = None,
) -> dict:
    """
    Sends path + tool results to DA Agent. Returns parsed response dict.
    Raises ValueError if JSON is malformed.
    Raises Exception for API failures.
    """
    context = build_da_context(current_path, tool_results, cross_path_summary, column_skewness)

    response = with_backoff(
        client.messages.create,
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        system=DA_SYSTEM_PROMPT,
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
        raise ValueError(f"DA Agent returned invalid JSON: {e}\nRaw output: {raw_text}")


# ══════════════════════════════════════════════════════════════════════
# BLOCK 5 — GATE RUNNER
# Called from app.py. Never raises — returns error dict on failure.
# ══════════════════════════════════════════════════════════════════════


def run_da_agent(
    current_path: dict,
    tool_results: list[dict],
    cross_path_summary: dict | None = None,
    column_skewness: dict | None = None,
) -> dict:
    """
    Full DA gate execution.
    Returns validated findings dict on success.
    Returns error dict on failure — never raises.
    """
    try:
        raw = call_da_agent(current_path, tool_results, cross_path_summary, column_skewness)
        findings = DAFindings(**raw)
        return findings.model_dump()

    except ValidationError as e:
        return {"error": "validation_failed", "detail": str(e)}
    except ValueError as e:
        return {"error": "invalid_json", "detail": str(e)}
    except Exception as e:
        return {"error": "api_failure", "detail": str(e)}
