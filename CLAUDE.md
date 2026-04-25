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
| [profiler.py](profiler.py) | Hardcoded pandas profiler — `get_dataset_profile(df)` returns metadata dict |
| [de_agent.py](de_agent.py) | Data Engineer LLM agent — interprets profiler output, returns quality JSON |
| [pm_agent.py](pm_agent.py) | PM orchestrator agent — gates stage transitions, generates user-facing summaries |
| [researcher_agent.py](researcher_agent.py) | Researcher LLM agent — generates exactly 5 research paths, each with 2–5 ordered `ToolInstruction` objects |
| [starter_kit.py](starter_kit.py) | 10 hardcoded analysis functions + `TOOL_MAP` registry |
| [switchboard.py](switchboard.py) | Validates and dispatches `ToolInstruction` JSON to `TOOL_MAP` functions |

### Pipeline stages

```
START → AUDIT → RESEARCH → ANALYSIS → DASHBOARD
```

`st.session_state.stage` is the router. `app.py` renders different UI blocks based on the current stage. See [session_state_registry.md](session_state_registry.md) for the full list of session_state keys and their schemas.

### Agent module structure

Every agent file follows the same block pattern:

1. **System prompt** — injected on every call; agents are stateless
2. **Pydantic models** — validate LLM JSON output before it enters session_state; `@field_validator` used for cross-field constraints (e.g. exact path count, valid tool names)
3. **Context builder** (`build_*_context`) — assembles the user-turn string from available session data
4. **`call_*` function** — hits the Anthropic API, strips markdown fences, parses JSON
5. **`run_*` gate function** — the only function `app.py` imports; never raises, returns error dict on failure

The Researcher Agent has one additional pattern: `TOOL_SIGNATURES` dict injected into the context prompt so the LLM knows accepted param names per tool, preventing hallucinated params.

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

The project follows a 15-stage build plan detailed in [DIG ANALYTICS CLAUDE.md](DIG%20ANALYTICS%20CLAUDE.md). **Current stage: 10 — DA / Stats Agent.** Stages 1–9 are complete.

Next to build: DA/Stats Agent — receives the selected research path + accumulated Starter Kit tool results, interprets them statistically, and returns a findings JSON with insight, supporting stats, and a recommended visualization type.
