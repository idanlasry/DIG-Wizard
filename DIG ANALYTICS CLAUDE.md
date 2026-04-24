# DIG Analytics Agent — Claude Context File
> This file is the shared context layer between Claude.ai and Claude Code sessions.
> Always read this first before making changes to any agent prompt or project file.

---

## What We're Building

**DIG** = Description → Introspection → Goal Setting

A multi-agent data analysis platform. User uploads a CSV → hardcoded pandas layer extracts facts → 5 specialized LLM agents interpret and analyze → PM agent orchestrates the pipeline via a cyberpunk Streamlit UI → final output is a **Consolidated Living Report** + interactive Plotly dashboard.

---

## Tech Stack

| Layer | Tool | Role |
|-------|------|------|
| UI | Streamlit + custom CSS | Cyberpunk 3-column layout |
| Data layer | Pandas | All math, counting, profiling — never LLM |
| Orchestration | Python (parametric function calling) | LLM triggers pre-written modules |
| LLM — PM / Synthesis | Anthropic (Claude Sonnet) | Orchestration, synthesis, report writing |
| LLM — Utility / Formatting | OpenAI (GPT-4o mini) | Cheaper utility calls |
| Validation | Pydantic v2 | Validate all LLM JSON outputs |
| State | Streamlit session_state | Pipeline memory across reruns |
| Env management | uv | Fast dependency resolution |
| Deployment | Streamlit Cloud | Free public sharing |

---

## The 5 Agents

| # | Agent | DIG Stage | Responsibility |
|---|-------|-----------|----------------|
| 1 | 💬 PM Agent | Orchestrator | Gates transitions, passes context, synthesizes findings |
| 2 | 🔧 Data Engineer | D — Description | Interprets pandas profiler output — quality score, issues, outliers |
| 3 | 📊 Stats Expert | I — Introspection | Correlations, trends, distributions, statistical patterns |
| 4 | 🔍 Researcher | I — Introspection | Generates 5 high-value answerable business research paths, each containing an ordered list of 3–5 Starter Kit tool instructions |
| 5 | 📈 BI Developer | G — Goal Setting | Maps DA results to Plotly chart configs |

---

## Pipeline Flow

```
CSV Upload (up to 20MB)
    ↓
[HARDCODED] Pandas Profiler runs → schema, nulls, outliers, distributions
    ↓
[LLM] Data Engineer interprets profiler output → quality score + issues JSON
    ↓
[PM GATE 1] PM summarizes findings → user confirms or adds note
    ↓
[LLM] Researcher generates 5 research paths → user selects one
    ↓
[HARDCODED] Starter Kit function runs based on selected path
    ↓
[LLM] Stats Expert / DA Agent interprets results → findings JSON
    ↓
[LLM] Synthesis Engine updates Living Report
    ↓
[USER] Select new path OR proceed to dashboard
    ↓
[LLM] BI Developer builds Plotly chart configs → rendered in UI
```

---

## Architecture Decisions

| Decision | Choice |
|----------|--------|
| Data processing | Pandas only — LLM never sees raw CSV |
| CSV sampling | <5k rows: full metadata + head/tail · >5k rows: metadata + 250 first + 250 last + 500 random |
| LLM output format | Strict JSON — Pydantic validates every response |
| Orchestration model | Parametric — Python controls flow, LLM triggers named functions |
| Agent memory | Stateless — PM passes full context explicitly to each call |
| State persistence | Streamlit session_state — history log, master report, stage router |
| Cost strategy | GPT-4o mini for utility · Claude Sonnet for synthesis/PM only |
| Sharing | Streamlit Cloud — free public URL, no auth for MVP |
| Research path tool execution | 3–5 Starter Kit tools run per research path, sequentially. Researcher Agent returns an ordered list of ToolInstruction objects. Each passes through the Switchboard independently. Results accumulate in a list and are passed together to the DA Agent for interpretation. MVP will be built with single-tool paths first, then expanded to multi-tool lists once the full pipeline is working end to end. |

---

## Session Process Protocol

```
1. Build stage with Claude Code (fast)
2. Study the code + concepts with chat AI (understand what was built)
3. Refine if needed
4. Move to next stage
```

**Rule:** Don't move to the next stage until you can explain the current one in plain English.

---

## 15-Stage Build Plan

### Phase 1: Foundation (Stages 1–3) ✅ COMPLETE

---

#### Stage 1 — Environment & Repo Init ✅
**What was built:** uv project init, dependencies installed (streamlit, pandas, plotly, anthropic, openai, pydantic), .env for API keys, repo structure.

**Concepts to understand:**
- `uv` vs pip/conda — why faster, how lockfile works
- `.env` + `python-dotenv` — why API keys never go in code
- Project structure: what lives where and why

---

#### Stage 2 — Core State Management ✅
**What was built:** `st.session_state` initialization block — stage router (`START → AUDIT → RESEARCH → ANALYSIS → DASHBOARD`), history_logs list, master_report string, raw_data and metadata holders, `add_log()` helper function.

**Concepts to understand:**
- Why Streamlit reruns the entire script on every interaction
- What `session_state` solves — persistence across reruns
- The stage string as a router — how `if stage == "AUDIT"` controls what renders
- Why `if "initialized" not in st.session_state` prevents resetting on rerun

---

#### Stage 3 — Cyberpunk UI Shell ✅
**What was built:** CSS injection via `st.markdown(unsafe_allow_html=True)`, 3-column layout (`st.columns([1,2,1])`), system logs terminal (col 1), command center with stage-based routing (col 2), living report panel (col 3), footer status bar.

**Concepts to understand:**
- How Streamlit renders custom CSS via markdown injection
- `st.columns()` — layout splitting
- `st.container(height=..., border=True)` — scrollable bounded panels
- How the log loop renders colored terminal output with f-strings

---

### Phase 2: The Hardcoded Core (Stages 4–6)

---

#### Stage 4 — The Dataset Profiler 🔄 NEXT
**What to build:** Hardcoded pandas script that extracts everything the LLM needs — no AI involved. Triggered after CSV upload. Populates `st.session_state.metadata`.

**Output dict structure:**
```python
{
  "shape": (rows, cols),
  "is_sample": bool,
  "columns": [{"name": ..., "dtype": ..., "null_count": ..., "null_pct": ..., "sample_values": [...]}],
  "numeric_summary": {col: {"mean": ..., "std": ..., "min": ..., "max": ..., "outliers_zscore": [...], "outliers_iqr": [...]}},
  "categorical_summary": {col: {"unique_count": ..., "top_values": [...]}},
  "duplicate_rows": int,
  "full_row_count": int
}
```

**Concepts to understand:**
- `df.describe()`, `df.dtypes`, `df.isnull().sum()` — pandas profiling basics
- Z-score outlier detection: `(x - mean) / std > 3`
- IQR outlier detection: `Q3 + 1.5*IQR` upper fence
- Why we never send raw CSV to LLM — cost, token limits, privacy
- Smart sampling logic — why first+last+random is better than just random

---

#### Stage 5 — The Starter Kit Library ✅
**What was built:** 10 hardcoded pandas analysis functions in `starter_kit.py`. Each takes a df + optional params and returns a structured result dict with a "tool" key. Functions cover: simple aggregations (top_n_values, distribution_analysis, cross_tab), grouped math (correlation_matrix, segment_comparison, anomaly_detection), and time-based analysis (time_series_trend, rolling_average, cohort_retention, funnel_analysis). TOOL_MAP registry at bottom maps string names to function references for parametric dispatch. distribution_analysis updated to support optional filter_col and filter_val params for subset comparison (e.g. churners vs non-churners).

**What to build:** 10 modular pandas functions, each takes `df` + optional params, returns a structured result dict. These are the "tools" the DA Agent will trigger by name.

**Functions to build:**
1. `correlation_matrix(df, columns)` — top correlations
2. `time_series_trend(df, date_col, value_col)` — trend over time
3. `segment_comparison(df, group_col, value_col)` — group means/counts
4. `distribution_analysis(df, col)` — histogram bins + skewness
5. `top_n_values(df, col, n)` — frequency ranking
6. `cohort_retention(df, date_col, id_col)` — retention matrix
7. `funnel_analysis(df, stage_cols)` — conversion rates
8. `anomaly_detection(df, col)` — flag unusual values
9. `cross_tab(df, col1, col2)` — pivot frequency table
10. `rolling_average(df, date_col, value_col, window)` — smoothed trend

**Concepts to understand:**
- Why these are hardcoded, not LLM-generated — deterministic, free, auditable
- How a function registry works — `TOOL_MAP = {"correlation": correlation_matrix, ...}`
- Return dict structure — every function returns same shape so UI can render uniformly

---

#### Stage 6 — Tool Switchboard ✅
**What was built:** `switchboard.py` — validates LLM tool instructions via Pydantic (ToolInstruction model), checks tool exists in TOOL_MAP, executes the matching function with unpacked params. Three error states: invalid_instruction, unknown_tool, execution_failed. Returns result dict or error dict with detail.

**What to build:** Controller that receives a JSON instruction from the DA Agent (`{"tool": "correlation_matrix", "params": {"columns": ["revenue", "churn"]}}`) and maps it to the correct Starter Kit function.

**Concepts to understand:**
- Parametric function calling vs agentic tool use — you control the flow
- Why LLM outputs tool name + params as JSON, Python executes
- Error handling — what if LLM hallucinates a tool name that doesn't exist
- Pydantic model for validating the tool instruction before executing

---

### Phase 3: Agent Orchestration (Stages 7–10)

---

#### Stage 7 — PM Agent (Concierge) ⏳
**What to build:** The most important agent. Greeting logic, stage gate transitions, context passing. Receives summary of previous stage output and generates the user-facing message + next action options.

**Concepts to understand:**
- Why PM is stateless but must carry full history — what gets injected into each call
- System prompt design for an orchestrator role
- How to pass structured context without blowing up the context window
- Gate pattern — PM decides if output is good enough to proceed

---

#### Stage 8 — Data Engineer Agent ⏳
**What to build:** LLM call that receives the pandas profiler output dict (Stage 4) and returns the finalized quality JSON. Prompt already written — wire it to the API with Pydantic validation.

**Prompt status:** ✅ FINALIZED (see Prompt Library below)

**Concepts to understand:**
- How to pass a Python dict as LLM context — `json.dumps(metadata)`
- Pydantic model matching the DE output schema
- Retry logic — what happens if LLM returns malformed JSON

---

#### Stage 9 — Researcher Agent ⏳
**What to build:** Receives profiler output + DE findings → generates exactly 5 answerable business research paths as JSON. User selects one path → triggers Stage 6 tool switchboard.

**Concepts to understand:**
- What makes a research question "answerable" with the available data
- How to constrain LLM output to exactly N items with Pydantic
- Rendering clickable path options in Streamlit

---

#### Stage 10 — DA / Stats Agent ⏳
**What to build:** Receives selected research path + Starter Kit output → interprets results → returns findings JSON with insight, supporting stats, and recommended visualization type.

**Concepts to understand:**
- How to chain: user selection → tool call → LLM interpretation
- Why DA agent never does math — it only interprets what pandas returned
- Findings JSON schema design

---

### Phase 4: Synthesis & Visualization (Stages 11–13)

---

#### Stage 11 — BI Developer Agent ⏳
**What to build:** Receives DA findings + visualization recommendation → returns Plotly chart config as JSON → Python renders it.

**Concepts to understand:**
- Plotly chart config structure — why JSON → chart is cleaner than LLM writing Plotly code
- Chart type selection logic — when bar vs line vs scatter vs heatmap
- How to render Plotly in Streamlit (`st.plotly_chart()`)

---

#### Stage 12 — Synthesis Engine (Living Report) ⏳
**What to build:** "Lead Editor" LLM call that rewrites the master report after each research path. Receives all previous path summaries + new findings → outputs updated markdown report.

**Concepts to understand:**
- Iterative report synthesis — how to append without losing context
- Token management — summarize old paths before passing to new call
- Why the report lives in `session_state.master_report`

---

#### Stage 13 — Iterative Research Loop ⏳
**What to build:** "New Path" button logic — user can run multiple research paths without losing previous findings. Loop control in session_state.

**Concepts to understand:**
- State machine pattern — how stage transitions work in a loop
- Appending to `analysis_results` list in session_state
- UI for showing previous paths + current path simultaneously

---

### Phase 5: Polish & Deploy (Stages 14–15)

---

#### Stage 14 — Validation & Error Handling ⏳
**What to build:** Pydantic models for all LLM outputs, exponential backoff wrapper for API calls, graceful error display in UI.

**Concepts to understand:**
- Exponential backoff — why and how (tenacity library or manual)
- Pydantic v2 model_validate vs model_json
- User-facing error messages vs internal logs

---

#### Stage 15 — Deployment ⏳
**What to build:** Streamlit Cloud deployment, secrets management (no .env in cloud), README for portfolio, LinkedIn post draft.

**Concepts to understand:**
- Streamlit Cloud secrets — how they replace .env
- `requirements.txt` vs `pyproject.toml` for deployment
- Portfolio framing: business problem first, not stack first

---

## Prompt Library

### ✅ Agent 2: Data Engineer (FINALIZED)

```
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
```

### 🔄 Agent 4: Researcher — NOT STARTED
### 🔄 Agent 3: Stats Expert / DA — NOT STARTED
### 🔄 Agent 1: PM Agent — NOT STARTED
### 🔄 Agent 5: BI Developer — NOT STARTED

---

## Current Status

**Active stage:** Stage 7 — PM Agent
**Stages complete:** 1, 2, 3, 4, 5, 6
**Stages remaining:** 4–15
**Deployment target:** Streamlit Cloud (free, shareable URL)
**Build environment:** VS Code + Claude Code
**Study environment:** Claude.ai chat / Gemini

---

## Key Design Principles

- **Pandas does the counting, AI does the thinking** — LLM never sees raw CSV
- **Prompts ARE the intelligence** — the app is just plumbing
- **PM Agent is the most critical** — it holds context across all stateless agent calls
- **Parametric over agentic** — Python controls flow, LLM triggers named functions
- **MVP = ship the core loop first** — resist features until Stages 1–13 work end-to-end
- **Own every number** — if pandas produced it, you can verify it; if LLM produced it, validate with Pydantic
- **Slow is smooth, smooth is fast** — understand each stage before building the next