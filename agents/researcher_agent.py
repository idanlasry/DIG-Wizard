# researcher_agent.py
import json
from anthropic import Anthropic
from pydantic import BaseModel, ValidationError, field_validator, model_validator
import streamlit as st
from utils.utils import with_backoff, calculate_cost

client = Anthropic()

# ══════════════════════════════════════════════════════════════════════
# BLOCK 1 — SYSTEM PROMPT
# Researcher Agent identity and output rules.
# Stateless — receives full metadata + DE findings on every call.
# Knows which tools exist. Plans paths. Never executes them.
# ══════════════════════════════════════════════════════════════════════

RESEARCHER_SYSTEM_PROMPT = """
You are a senior data analyst specializing in exploratory research planning.

Your job: given a dataset profile and quality findings, generate exactly 5 high-value,
answerable business research paths. Also identify the dataset's primary outcome metric.

Each path must:
- Address a real business question answerable with the available columns
- Only propose a path if the combined output of all tool instructions is sufficient to answer the question
- Use between 2 and 5 tools from the provided AVAILABLE_TOOLS list
- Order tool instructions logically (e.g. segment first, then correlate within segment)
- Only reference columns that exist in the dataset profile

Additionally, identify the dataset's primary outcome metric — the binary variable most likely
being analyzed as the target (churn, conversion, fraud, default, etc.). Detect binary columns
by finding numeric columns where min=0 and max=1. Choose the one most central to the business
question. If no binary column exists, set primary_metric to null.

Respond with ONLY a valid JSON object. No explanation, no markdown, no code blocks.

Use exactly this structure:

{
  "primary_metric": {
    "label": "<human-readable rate name, e.g. 'Conversion Rate', 'Churn Rate', 'Fraud Rate'>",
    "column": "<exact column name from the dataset>",
    "rate_pct": <mean * 100 as a float with one decimal, e.g. 35.2>
  },
  "paths": [
    {
      "title": "<short path name, 3-6 words>",
      "question": "<one clear business question this path answers>",
      "tool_instructions": [
        {
          "tool": "<exact tool name from AVAILABLE_TOOLS>",
          "params": { "<param_name>": "<param_value>" }
        }
      ]
    }
  ],
  "user_interest_path": null
}

If no binary outcome column exists, use: "primary_metric": null

Rules:
- Return between 3 and 5 paths. If the dataset does not support 5 truly distinct paths, return 3 or 4 — never pad with redundant ones.
- Each path must have between 2 and 5 tool_instructions.
- tool names must exactly match one of the AVAILABLE_TOOLS provided.
- params must match what each tool actually accepts — do not invent param names.

PATH ORTHOGONALITY — this is the most important constraint:
- Each path must cover a different business dimension (e.g. churn drivers, financial risk, geographic patterns, demographic segmentation, product behaviour). No two paths may address the same business question from a different angle.
- Every path must use at least one tool that does not appear in any other path. A path whose entire tool list is a subset of another path's tools is forbidden.
- If you cannot find enough orthogonal paths given the available columns, reduce the count rather than returning overlapping paths.

USER INTEREST PATH (conditional):
If a USER_INTEREST section appears in the context, populate "user_interest_path" instead of leaving it null.
This path is IN ADDITION to the required 3–5 paths above — do not replace a regular path with it.
Think carefully before filling it in:

  FEASIBLE (the dataset has relevant columns AND the available tools can answer it):
    → Set "title" (3–6 words), "question" (one clear business question),
      "rationale" (2–4 sentences: what you'll check, why it matters, what insight the tools will surface),
      "tool_instructions" (2–5 tools, ordered logically), and leave "feasibility_note" as null.

  NOT FEASIBLE (no relevant columns, no applicable tools, or the question is outside what the data can answer):
    → Set "title", "question", "rationale" (explain what the user was asking about),
      "feasibility_note" (explain specifically why the dataset/tools cannot answer it),
      and leave "tool_instructions" as null.

- Never add fields outside this schema.
- Never return text outside the JSON object.
"""

# ══════════════════════════════════════════════════════════════════════
# BLOCK 2 — PYDANTIC VALIDATION MODELS
# Validates Researcher output before it enters session_state.
# Catches wrong tool names, missing fields, wrong path count.
# ══════════════════════════════════════════════════════════════════════

# Tool names that actually exist in TOOL_MAP
VALID_TOOLS = {
    "correlation_matrix",
    "time_series_trend",
    "segment_comparison",
    "distribution_analysis",
    "top_n_values",
    "cohort_retention",
    "funnel_analysis",
    "anomaly_detection",
    "cross_tab",
    "rolling_average",
}


class ResearchToolInstruction(BaseModel):
    tool: str
    params: dict

    @field_validator("tool")
    @classmethod
    def tool_must_be_valid(cls, v):
        if v not in VALID_TOOLS:
            raise ValueError(
                f"'{v}' is not a valid tool. Must be one of: {sorted(VALID_TOOLS)}"
            )
        return v


class ResearchPath(BaseModel):
    title: str
    question: str
    tool_instructions: list[ResearchToolInstruction]

    @field_validator("tool_instructions")
    @classmethod
    def must_have_two_to_five_tools(cls, v):
        if not (2 <= len(v) <= 5):
            raise ValueError(f"Each path must have 2–5 tool instructions, got {len(v)}")
        return v


class PrimaryMetric(BaseModel):
    label: str    # e.g. "Conversion Rate", "Churn Rate"
    column: str   # exact column name in the dataset
    rate_pct: float  # mean * 100


class UserInterestPath(BaseModel):
    title: str
    question: str
    rationale: str  # what this path checks, why it matters, what insight it gives
    tool_instructions: list[ResearchToolInstruction] | None = None
    feasibility_note: str | None = None  # set when dataset/tools can't answer the interest

    @model_validator(mode="after")
    def must_have_tools_or_note(self):
        if not self.tool_instructions and not self.feasibility_note:
            raise ValueError(
                "UserInterestPath must have either tool_instructions or feasibility_note"
            )
        return self


class ResearcherOutput(BaseModel):
    primary_metric: PrimaryMetric | None = None
    paths: list[ResearchPath]
    user_interest_path: UserInterestPath | None = None

    @field_validator("paths")
    @classmethod
    def must_have_three_to_five_paths(cls, v):
        if not (3 <= len(v) <= 5):
            raise ValueError(f"Researcher must return 3–5 paths, got {len(v)}")
        return v


# ══════════════════════════════════════════════════════════════════════
# BLOCK 3 — CONTEXT BUILDER
# Serializes metadata + DE findings into a structured prompt string.
# Injects available tool names + their accepted params so the LLM
# can plan valid tool calls without hallucinating param names.
# ══════════════════════════════════════════════════════════════════════

# Tool signatures injected into context so LLM knows what params each tool accepts.
# Kept minimal — just enough to prevent hallucinated param names.
TOOL_SIGNATURES = {
    "correlation_matrix": "params: columns (list of column names, optional)",
    "time_series_trend": "params: date_col (str), value_col (str)",
    "segment_comparison": "params: group_col (str), value_col (str)",
    "distribution_analysis": "params: col (str)",
    "top_n_values": "params: col (str), n (int, optional, default 10)",
    "cohort_retention": "params: date_col (str), id_col (str)",
    "funnel_analysis": "params: stage_cols (list of column names)",
    "anomaly_detection": "params: col (str)",
    "cross_tab": "params: col1 (str), col2 (str)",
    "rolling_average": "params: date_col (str), value_col (str), window (int, optional, default 7)",
}


def build_researcher_context(
    metadata: dict, de_findings: dict, user_interest: str | None = None
) -> str:
    """
    Builds the user-turn message for the Researcher Agent.
    Includes: dataset shape, column list, numeric/categorical summaries,
    DE quality issues, and available tools with their param signatures.
    """
    parts = []

    # Dataset shape
    shape = metadata.get("shape", {})
    parts.append(
        f"DATASET: {shape.get('rows', '?')} rows × {shape.get('cols', '?')} columns"
    )
    parts.append(f"Duplicate rows: {metadata.get('duplicate_rows', '?')}")

    # Column list with dtypes
    cols = metadata.get("columns", [])
    col_lines = [
        f"  - {c['name']} ({c['dtype']}) — nulls: {c['null_pct']}%" for c in cols
    ]
    parts.append("COLUMNS:\n" + "\n".join(col_lines))

    # Numeric summary (mean/min/max so LLM knows the scale)
    num_summary = metadata.get("numeric_summary", {})
    if num_summary:
        num_lines = []
        for col, stats in num_summary.items():
            num_lines.append(
                f"  - {col}: mean={stats['mean']}, min={stats['min']}, max={stats['max']}, "
                f"IQR outliers={stats['outliers_iqr_count']}"
            )
        parts.append("NUMERIC SUMMARY:\n" + "\n".join(num_lines))

    # Categorical summary (unique counts + top values)
    cat_summary = metadata.get("categorical_summary", {})
    if cat_summary:
        cat_lines = []
        for col, info in cat_summary.items():
            top = list(info["top_values"].keys())[:3]
            cat_lines.append(
                f"  - {col}: {info['unique_count']} unique values. Top: {', '.join(top)}"
            )
        parts.append("CATEGORICAL SUMMARY:\n" + "\n".join(cat_lines))

    # DE quality issues (so Researcher avoids broken columns)
    issues = de_findings.get("quality_issues", [])
    if issues:
        issue_lines = [
            f"  - {i['issue']} ({i['affected_column']}): {i['detail']}" for i in issues
        ]
        parts.append("QUALITY ISSUES TO AVOID:\n" + "\n".join(issue_lines))
    else:
        parts.append("QUALITY ISSUES: None detected.")

    # Available tools with param signatures
    tool_lines = [f"  - {name}: {sig}" for name, sig in TOOL_SIGNATURES.items()]
    parts.append("AVAILABLE_TOOLS:\n" + "\n".join(tool_lines))

    if user_interest:
        parts.append(
            f"--- USER INTEREST ---\n"
            f'The user has flagged a specific area they want explored:\n'
            f'"{user_interest}"\n'
            f"Reflect on this in your user_interest_path output object (see instructions above)."
        )

    parts.append(
        "Based on the above, generate 3–5 orthogonal research paths as a JSON object."
    )

    return "\n\n".join(parts)


# ══════════════════════════════════════════════════════════════════════
# BLOCK 4 — THE RESEARCHER CALL
# Sends context to Claude → parses JSON → returns raw dict.
# Strips markdown fences defensively.
# Caller handles validation and errors.
# ══════════════════════════════════════════════════════════════════════


def call_researcher_agent(
    metadata: dict, de_findings: dict, user_interest: str | None = None
) -> dict:
    """
    Sends profiler metadata + DE findings to the Researcher Agent.
    Returns parsed response dict.
    Raises ValueError if JSON is malformed.
    Raises Exception for API failures.
    """
    context = build_researcher_context(metadata, de_findings, user_interest)

    response = with_backoff(
        client.messages.create,
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
        system=RESEARCHER_SYSTEM_PROMPT,
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
            f"Researcher Agent returned invalid JSON: {e}\nRaw output: {raw_text}"
        )


# ══════════════════════════════════════════════════════════════════════
# BLOCK 4b — DEDUPLICATION HELPER
# Removes paths whose entire tool set is a subset of other paths' tools.
# Stops when only 3 paths remain so we never drop below the minimum.
# ══════════════════════════════════════════════════════════════════════


def deduplicate_paths(paths: list[dict]) -> list[dict]:
    kept = list(paths)
    changed = True
    while changed and len(kept) > 3:
        changed = False
        for i, path in enumerate(kept):
            path_tools = {ti["tool"] for ti in path["tool_instructions"]}
            other_tools = {
                ti["tool"]
                for j, p in enumerate(kept)
                if j != i
                for ti in p["tool_instructions"]
            }
            if not (path_tools - other_tools):  # no unique tools → redundant
                kept.pop(i)
                changed = True
                break
    return kept


# ══════════════════════════════════════════════════════════════════════
# BLOCK 5 — GATE RUNNER
# High-level function called from app.py.
# Calls Researcher → validates with Pydantic → returns clean dict.
# On failure returns error dict — never raises.
# ══════════════════════════════════════════════════════════════════════


def run_researcher_agent(
    metadata: dict, de_findings: dict, user_interest: str | None = None
) -> dict:
    """
    Full Researcher gate execution.
    Returns validated output dict on success:
      {"paths": [...], "primary_metric": ..., "user_interest_path": ...}
    Returns error dict on failure — never raises.
    """
    try:
        raw = call_researcher_agent(metadata, de_findings, user_interest)
        validated = ResearcherOutput(**raw)
        result = validated.model_dump()
        result["paths"] = deduplicate_paths(result["paths"])
        return result

    except ValidationError as e:
        return {"error": "validation_failed", "detail": str(e)}
    except ValueError as e:
        return {"error": "invalid_json", "detail": str(e)}
    except Exception as e:
        return {"error": "api_failure", "detail": str(e)}
