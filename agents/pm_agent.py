# pm_agent.py
import json
from anthropic import Anthropic
from pydantic import BaseModel, ValidationError, field_validator
import streamlit as st
from utils.utils import with_backoff, calculate_cost

client = Anthropic()


class PMResponse(BaseModel):
    user_message: str
    stage_transition: str | None
    ready_to_proceed: bool
    summary_for_log: str

    @field_validator("ready_to_proceed", mode="before")
    @classmethod
    def coerce_bool(cls, v):
        if isinstance(v, str):
            return v.strip().lower() == "true"
        return v

# ══════════════════════════════════════════════════════════════════════
# BLOCK 1 — SYSTEM PROMPT
# The PM Agent's identity and rules. Injected on every call.
# Stateless — no memory between calls. Context is passed explicitly.
# ══════════════════════════════════════════════════════════════════════
PM_SYSTEM_PROMPT = """
You are the PM Agent for DIG Analytics — a senior project manager and pipeline orchestrator.
You gate transitions between stages and communicate findings to the user.

You are stateless. Every call gives you full context. Never assume you remember previous calls.

PIPELINE:
START → AUDIT → RESEARCH → ANALYSIS → DASHBOARD

STAGE RULES:
- START → AUDIT: when CSV is uploaded and row count is confirmed
- AUDIT → RESEARCH: when DE findings are complete AND quality_score >= 5
- RESEARCH → ANALYSIS: when user has selected a research path
- ANALYSIS → ANALYSIS: when user selects a new path (loop continues)
- ANALYSIS → DASHBOARD: when user confirms they are done with research paths

At DASHBOARD gate: you receive all completed analysis paths as PREVIOUS FINDINGS.
Write user_message as a 2-3 sentence executive synthesis — what the data collectively shows,
the most important cross-path business insight, and what decision the stakeholder should act on.
Set ready_to_proceed to true. Set stage_transition to null.

At AUDIT gate: you will receive COLUMN_NAMES from the dataset. Use them to infer the
domain, key entities, and what types of analysis this data is suited for. Write this
as a brief opening paragraph in user_message — do NOT ask the user for context, infer
it yourself. Then summarize dataset size, quality score, key issues, and outliers in
plain English for a non-technical user.
Set ready_to_proceed to true if quality_score >= 5. Set it to false only if quality_score < 5,
and warn the user. Do not set ready_to_proceed to false for any other reason at this gate.

At RESEARCH gate: confirm the selected path title and research question in plain English.
Tell the analyst what to expect — which tools will run and what angle they cover.
When PREVIOUS FINDINGS is present in context, open user_message with a one-paragraph
synthesis of what's been found so far, then introduce the new path as "building on this."
Keep it tight. This becomes the living report header for this analysis cycle.

Your tone: professional, direct, cyberpunk. Short sentences. No fluff.
Always respond with ONLY a valid JSON object. No markdown. No explanation.

Response structure:
{
  "user_message": "<plain English message to show the user>",
  "stage_transition": "<next stage name, or null if staying>",
  "ready_to_proceed": <true or false>,
  "summary_for_log": "<one short sentence for the system log>"
}

Rules:
- user_message is what the user sees. Make it clear and actionable.
- stage_transition is null unless you are gating a move to the next stage.
- ready_to_proceed is true only when the current stage output is complete and valid.
- summary_for_log is internal. Keep it under 10 words.
- Never add fields outside this schema.
- Never return text outside the JSON object.
"""
# ══════════════════════════════════════════════════════════════════════
# BLOCK 2 — CONTEXT BUILDER
# Assembles the user message payload sent to the PM Agent.
# Takes whatever is currently known and packages it as a structured string.
# ══════════════════════════════════════════════════════════════════════


def build_pm_context(
    current_stage: str,
    metadata: dict = None,
    de_findings: dict = None,
    selected_path: dict = None,
    analysis_results: list = None,
    previous_findings: list = None,
    user_note: str = None,
) -> str:
    """
    Builds the user-turn message for the PM Agent.
    Only includes what's available — no KeyErrors on missing data.
    """
    parts = []

    parts.append(f"CURRENT_STAGE: {current_stage}")

    if metadata:
        shape = metadata.get("shape", {})
        col_names = [c["name"] for c in metadata.get("columns", []) if "name" in c]
        col_str = ", ".join(col_names) if col_names else "unknown"
        parts.append(
            f"DATASET: {shape.get('rows', '?')} rows, {shape.get('cols', '?')} columns. "
            f"Duplicate rows: {metadata.get('duplicate_rows', '?')}."
        )
        parts.append(f"COLUMN_NAMES: {col_str}")

    if de_findings:
        score = de_findings.get("quality_score", "?")
        issues = de_findings.get("quality_issues", [])
        parts.append(
            f"DE_FINDINGS: Quality score {score}/10. {len(issues)} issue(s) detected."
        )

    if previous_findings:
        finding_lines = []
        for i, item in enumerate(previous_findings, 1):
            da = item.get("da_findings", {})
            title = item.get("path", {}).get("title", "?")
            headline = da.get("headline", "?")
            insights = da.get("key_insights", [])[:3]
            finding_lines.append(
                f"Path {i} — {title}: {headline}. Key insights: {', '.join(insights)}."
            )
        parts.append("PREVIOUS FINDINGS:\n" + "\n".join(finding_lines))

    if selected_path:
        parts.append(
            f"SELECTED_PATH: {selected_path.get('title', '?')} — "
            f"{selected_path.get('question', '?')}"
        )

    if analysis_results:
        parts.append(
            f"COMPLETED_PATHS: {len(analysis_results)} path(s) analyzed so far."
        )

    if user_note:
        parts.append(f"USER_NOTE: {user_note}")

    parts.append("Based on the above, generate your PM response JSON.")

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════
# BLOCK 3 — THE PM CALL
# Single function that hits the Anthropic API and returns parsed JSON.
# Raw LLM text → parsed dict. Caller handles errors.
# ══════════════════════════════════════════════════════════════════════


def call_pm_agent(context_message: str) -> dict:
    """
    Sends context to PM Agent. Returns parsed response dict.
    Raises ValueError if JSON is malformed.
    Raises Exception for API failures.
    """
    response = with_backoff(
        client.messages.create,
        model="claude-haiku-4-5-20251001",  #! change to claude-sonnet-4-20250514 once mvp is done
        max_tokens=1000,
        system=PM_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context_message}],
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
        raise ValueError(f"PM Agent returned invalid JSON: {e}\nRaw output: {raw_text}")


# ══════════════════════════════════════════════════════════════════════
# BLOCK 4 — GATE RUNNER
# High-level function called from app.py.
# Builds context, calls PM, validates response shape, returns clean dict.
# This is the only function app.py needs to import.
# ══════════════════════════════════════════════════════════════════════

def run_pm_gate(
    current_stage: str,
    metadata: dict = None,
    de_findings: dict = None,
    selected_path: dict = None,
    analysis_results: list = None,
    previous_findings: list = None,
    user_note: str = None,
) -> dict:
    """
    Full PM gate execution.
    Returns response dict on success.
    Returns error dict on failure — never raises.
    """
    try:
        context = build_pm_context(
            current_stage=current_stage,
            metadata=metadata,
            de_findings=de_findings,
            selected_path=selected_path,
            analysis_results=analysis_results,
            previous_findings=previous_findings,
            user_note=user_note,
        )
        response = call_pm_agent(context)

        try:
            PMResponse(**response)
        except ValidationError as e:
            return {"error": "validation_failed", "detail": str(e)}

        return response

    except ValueError as e:
        return {"error": "invalid_json", "detail": str(e)}
    except Exception as e:
        return {"error": "api_failure", "detail": str(e)}
