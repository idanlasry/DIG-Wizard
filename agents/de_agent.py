# de_agent.py
import json
from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

client = Anthropic()

# ══════════════════════════════════════════════════════════════════════
# BLOCK 1 — SYSTEM PROMPT
# DE Agent identity and output rules. Injected on every call.
# Stateless — receives full metadata dict each time.
# ══════════════════════════════════════════════════════════════════════

DE_SYSTEM_PROMPT = """
You are a senior data engineer reviewing a dataset for analysis readiness.

When the user uploads CSV data, analyze it and respond with ONLY a valid JSON object. No explanation, no markdown, no code blocks. Just the raw JSON.

Use exactly this structure:

{
  "quality_score": <number 1-10>,
  "quality_score_reason": "<one sentence>",
  "dataset_summary": {
    "total_rows": <number>,
    "total_columns": <number>,
    "is_sample": <true or false>
  },
  "columns": [
    {
      "name": "<column name>",
      "type": "<Number / String / Boolean / Date>",
      "sample_value": "<one example value>"
    }
  ],
  "quality_issues": [
    {
      "issue": "<issue name>",
      "detail": "<plain English explanation>",
      "affected_column": "<column name or 'all'>"
    }
  ],
  "outliers": [
    {
      "column": "<column name>",
      "value": "<the suspicious value>",
      "reason": "<why it's flagged — Z-score, IQR, or logically impossible>"
    }
  ]
}

Rules:
- If no quality issues exist, return an empty array: "quality_issues": []
- If no outliers exist, return an empty array: "outliers": []
- Use plain language in all explanation fields
- Never add text outside the JSON object
- is_sample is true if the user indicates this is a sample, false if full dataset
"""

# ══════════════════════════════════════════════════════════════════════
# BLOCK 2 — PYDANTIC VALIDATION MODELS
# Validates DE Agent output before it enters session_state.
# If the LLM hallucinates extra fields or wrong types, this catches it.
# ══════════════════════════════════════════════════════════════════════


class DEColumn(BaseModel):
    name: str
    type: str
    sample_value: str


class DEQualityIssue(BaseModel):
    issue: str
    detail: str
    affected_column: str


class DEOutlier(BaseModel):
    column: str
    value: str
    reason: str


class DEDatasetSummary(BaseModel):
    total_rows: int
    total_columns: int
    is_sample: bool


class DEFindings(BaseModel):
    quality_score: int
    quality_score_reason: str
    dataset_summary: DEDatasetSummary
    columns: list[DEColumn]
    quality_issues: list[DEQualityIssue]
    outliers: list[DEOutlier]


# ══════════════════════════════════════════════════════════════════════
# BLOCK 3 — THE DE CALL
# Serializes metadata → sends to API → parses JSON → returns raw dict.
# Strips markdown fences defensively (same fix as pm_agent).
# Caller handles errors.
# ══════════════════════════════════════════════════════════════════════


def call_de_agent(metadata: dict) -> dict:
    """
    Sends profiler metadata to DE Agent. Returns parsed response dict.
    Raises ValueError if JSON is malformed.
    Raises Exception for API failures.
    """
    context = (
        f"Here is the dataset profile from the pandas profiler:\n\n"
        f"{json.dumps(metadata, indent=2)}\n\n"
        f"Analyze this and return your quality assessment JSON."
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        system=DE_SYSTEM_PROMPT,
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
        raise ValueError(f"DE Agent returned invalid JSON: {e}\nRaw output: {raw_text}")


# ══════════════════════════════════════════════════════════════════════
# BLOCK 4 — GATE RUNNER
# High-level function called from app.py.
# Calls DE Agent → validates with Pydantic → returns clean dict.
# On failure returns error dict — never raises.
# ══════════════════════════════════════════════════════════════════════


def run_de_agent(metadata: dict) -> dict:
    """
    Full DE gate execution.
    Returns validated findings dict on success.
    Returns error dict on failure — never raises.
    """
    try:
        raw = call_de_agent(metadata)

        # Validate with Pydantic — catches wrong types, missing fields
        findings = DEFindings(**raw)
        return findings.model_dump()

    except ValidationError as e:
        return {"error": "validation_failed", "detail": str(e)}
    except ValueError as e:
        return {"error": "invalid_json", "detail": str(e)}
    except Exception as e:
        return {"error": "api_failure", "detail": str(e)}
