# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the app
uv run streamlit run app.py

# Install dependencies
uv sync

# Add a dependency
uv add <package>
```

There are no automated tests. Manual testing means uploading a CSV via the Streamlit UI and verifying agent output in the Living Report panel.

## Architecture

**DIG** (Description → Introspection → Goal Setting) is a multi-agent data analysis platform. Users upload a CSV; a hardcoded pandas layer extracts facts; specialized LLM agents interpret results; a cyberpunk Streamlit UI presents everything.

**Core constraint:** LLM agents never see the raw CSV. They only receive structured profiler output passed as `json.dumps(metadata)`.

### Source files

| File | Role |
|------|------|
| [app.py](app.py) | Entry point. 3-column Streamlit layout, stage router, session_state init |
| [core/profiler.py](core/profiler.py) | Hardcoded pandas profiler — `get_dataset_profile(df)` returns metadata dict |
| [core/starter_kit.py](core/starter_kit.py) | 10 hardcoded analysis functions + `TOOL_MAP` registry |
| [core/switchboard.py](core/switchboard.py) | Validates and dispatches `ToolInstruction` JSON to `TOOL_MAP` functions |
| [agents/de_agent.py](agents/de_agent.py) | Data Engineer LLM agent — interprets profiler output, returns quality JSON |
| [agents/pm_agent.py](agents/pm_agent.py) | PM orchestrator agent — gates stage transitions, generates user-facing summaries |
| [agents/researcher_agent.py](agents/researcher_agent.py) | Researcher LLM agent — generates 3–5 orthogonal research paths, each with 2–5 ordered `ToolInstruction` objects; also accepts an optional `user_interest` string and appends a `user_interest_path` to the output (feasible path or infeasibility explanation) |
| [agents/da_agent.py](agents/da_agent.py) | Data Analyst LLM agent — interprets tool results, explains business meaning |
| [agents/bi_agent.py](agents/bi_agent.py) | BI Developer LLM agent — generates KPIs and Plotly chart configs from findings |
| [agents/synthesis_agent.py](agents/synthesis_agent.py) | Synthesis LLM agent — cross-path narrative + actionable recommendations |
| [utils/utils.py](utils/utils.py) | `with_backoff()` retry helper and `calculate_cost()` for token cost tracking |

### Pipeline stages

```
START → AUDIT → RESEARCH → ANALYSIS → DASHBOARD
```

`st.session_state.stage` is the router. `app.py` renders different UI blocks based on the current stage. See [docs/session_state_registry.md](docs/session_state_registry.md) for the full list of session_state keys and their schemas.

### Agent module structure

Every agent file follows the same block pattern:

1. **System prompt** — injected on every call; agents are stateless
2. **Pydantic models** — validate LLM JSON output before it enters session_state; `@field_validator` used for cross-field constraints (e.g. exact path count, valid tool names)
3. **Context builder** (`build_*_context`) — assembles the user-turn string from available session data
4. **`call_*` function** — hits the Anthropic API, strips markdown fences, parses JSON
5. **`run_*` gate function** — the only function `app.py` imports; never raises, returns error dict on failure

The Researcher Agent has two additional patterns:
- `TOOL_SIGNATURES` dict injected into the context prompt so the LLM knows accepted param names per tool, preventing hallucinated params.
- Optional `user_interest` string passed from the UI. When present, a `USER_INTEREST` section is appended to the context and the LLM outputs a `user_interest_path` object alongside the regular paths. The path includes a `rationale` and either `tool_instructions` (feasible) or a `feasibility_note` (not feasible given the dataset/tools). Validated by `UserInterestPath` Pydantic model.

### LLM models

Both agents currently use `claude-haiku-4-5-20251001` for MVP speed. PM Agent has a `#!` comment to switch to `claude-sonnet-4-20250514` post-MVP.

### Tool dispatch pattern

The Researcher Agent returns `ToolInstruction` objects `{"tool": "<name>", "params": {...}}`. [switchboard.py](switchboard.py) validates via Pydantic, looks up the function in `TOOL_MAP`, and executes with unpacked params. Results accumulate in `st.session_state.analysis_results`.

## Key design rules

- **Pandas counts, LLM thinks** — all arithmetic stays in profiler/starter_kit; agents only interpret
- **Parametric over agentic** — Python controls flow; LLM triggers named functions by name
- **PM Agent is stateless but context-complete** — `build_pm_context()` assembles everything needed into one string before each call
- **Every LLM output is Pydantic-validated** — if validation fails, the gate runner returns `{"error": ..., "detail": ...}` and the UI shows the error inline

## Build status

The project follows a 15-stage build plan detailed in [docs/DIG ANALYTICS CLAUDE.md](docs/DIG%20ANALYTICS%20CLAUDE.md). **Current stage: 10 — DA / Stats Agent.** Stages 1–9 are complete.

Stage 10 multi-path loop support is complete: `pm_summaries` accumulates all PM messages, `analysis_results` accumulates all DA findings, the 3-path cap is enforced in the ANALYSIS nav block, and the PM Agent receives `previous_findings` context for synthesis paragraphs at path N>1. The report panel now has 5 tabs including DA FINDINGS (multi-path) and PM LOG.

**Post-stage-10 addition:** User interest nudge before research. At the end of AUDIT, the user can optionally type a free-text area of interest. The Researcher Agent receives it as a `USER_INTEREST` context section and appends a `user_interest_path` to its output — either a fully planned path (with `rationale` + `tool_instructions`) or an infeasibility note. Stored in `st.session_state.user_interest_path`; displayed as a distinct card at the top of the RESEARCH stage.

Next to build: Stage 11 — BI Developer Agent (Plotly chart config from DA findings).
