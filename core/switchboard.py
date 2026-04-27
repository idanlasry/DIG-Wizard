# switchboard.py
import json
from pydantic import BaseModel, ValidationError
from typing import Any
import pandas as pd
from starter_kit import TOOL_MAP


# ── 1. PYDANTIC VALIDATION MODEL ───────────────────────────────────────
class ToolInstruction(BaseModel):
    tool: str
    params: dict[str, Any] = {}


# ── 2. CORE SWITCHBOARD FUNCTION ───────────────────────────────────────
def run_tool(instruction_json: dict, df: pd.DataFrame) -> dict:
    """
    Receives a JSON instruction from the Researcher Agent.
    Validates it, looks up the function in TOOL_MAP, executes it.
    Returns the result dict or an error dict.
    """
    # Step 1 — Validate structure
    try:
        instruction = ToolInstruction(**instruction_json)
    except ValidationError as e:
        return {"error": "invalid_instruction", "detail": str(e)}

    # Step 2 — Check tool exists
    if instruction.tool not in TOOL_MAP:
        return {
            "error": "unknown_tool",
            "detail": f"'{instruction.tool}' not found in TOOL_MAP.",
            "available_tools": list(TOOL_MAP.keys()),
        }

    # Step 3 — Execute
    try:
        func = TOOL_MAP[instruction.tool]
        result = func(df, **instruction.params)
        return result
    except TypeError as e:
        return {"error": "bad_params", "detail": str(e)}
    except Exception as e:
        return {"error": "execution_failed", "detail": str(e)}
