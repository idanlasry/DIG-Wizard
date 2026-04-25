# pm_agent.py
import os
import json
from urllib import response
from anthropic import Anthropic

client = Anthropic()

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

At AUDIT gate: translate DE findings into plain English for a non-technical user.
Summarize dataset size, quality score, key issues, and outliers in user_message.
If quality_score < 5, do not proceed to RESEARCH. Warn the user and explain the issues.

At RESEARCH gate: user has selected a research path.
Confirm the selected path title and research question in plain English.
Tell the analyst what to expect — which tools will run and what angle they cover.
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
        parts.append(
            f"DATASET: {shape.get('rows', '?')} rows, {shape.get('cols', '?')} columns. "
            f"Duplicate rows: {metadata.get('duplicate_rows', '?')}."
        )

    if de_findings:
        score = de_findings.get("quality_score", "?")
        issues = de_findings.get("quality_issues", [])
        parts.append(
            f"DE_FINDINGS: Quality score {score}/10. {len(issues)} issue(s) detected."
        )

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
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",  #! change to laude-sonnet-4-20250514 once mvp is done
        max_tokens=1000,
        system=PM_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context_message}],
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

REQUIRED_KEYS = {
    "user_message",
    "stage_transition",
    "ready_to_proceed",
    "summary_for_log",
}


def run_pm_gate(
    current_stage: str,
    metadata: dict = None,
    de_findings: dict = None,
    selected_path: dict = None,
    analysis_results: list = None,
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
            user_note=user_note,
        )
        response = call_pm_agent(context)

        # Validate required keys are present
        missing = REQUIRED_KEYS - response.keys()
        if missing:
            return {
                "error": "incomplete_response",
                "detail": f"PM Agent missing keys: {missing}",
                "raw": response,
            }

        return response

    except ValueError as e:
        return {"error": "invalid_json", "detail": str(e)}
    except Exception as e:
        return {"error": "api_failure", "detail": str(e)}
