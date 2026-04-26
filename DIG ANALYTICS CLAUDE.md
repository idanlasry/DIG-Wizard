# DIG Analytics Agent — Claude Context File
> Shared context layer between Claude.ai and Claude Code sessions.
> Always read this first before making changes to any agent prompt or project file.

---

## What We're Building

**DIG** = Description → Introspection → Goal Setting

Multi-agent data analysis platform. User uploads a CSV → hardcoded pandas layer extracts facts → 5 specialized LLM agents interpret and analyze → PM agent orchestrates via a cyberpunk Streamlit UI → final output is a **Consolidated Living Report** + interactive Plotly dashboard.

---

## Tech Stack

| Layer | Tool | Role |
|-------|------|------|
| UI | Streamlit + custom CSS | Cyberpunk 3-column layout |
| Data layer | Pandas | All math, counting, profiling — never LLM |
| Orchestration | Python (parametric function calling) | LLM triggers pre-written modules |
| LLM | Anthropic Claude Haiku | All agent calls (upgrade to Sonnet post-MVP) |
| Validation | Pydantic v2 | Validate all LLM JSON outputs |
| State | Streamlit session_state | Pipeline memory across reruns |
| Env management | uv | Fast dependency resolution |
| Deployment | Streamlit Cloud | Free public sharing |

---

## The 5 Agents

| # | Agent | File | Responsibility |
|---|-------|------|----------------|
| 1 | 💬 PM Agent | `pm_agent.py` | Gates transitions, passes context, synthesizes findings |
| 2 | 🔧 Data Engineer | `de_agent.py` | Interprets profiler output — quality score, issues, outliers |
| 3 | 🔍 Researcher | `researcher_agent.py` | Generates 5 research paths with ordered tool instructions |
| 4 | 📊 DA / Stats Expert | `da_agent.py` | Interprets Starter Kit results — insights, stats, viz recommendation |
| 5 | 📈 BI Developer | `bi_agent.py` | Receives all analysis_results → decides KPIs + chart configs |

---

## Pipeline Flow

```
CSV Upload
    ↓
[HARDCODED] Pandas Profiler → schema, nulls, outliers, distributions → session_state.metadata
    ↓
[LLM] DE Agent → quality score + issues JSON → session_state.de_findings
    ↓
[PM GATE — AUDIT] Summarizes DE findings → user confirms
    ↓
[LLM] Researcher → 5 research paths → user selects one → session_state.current_path
    ↓
[PM GATE — RESEARCH] Confirms selected path → transitions to ANALYSIS
    ↓
[HARDCODED] Switchboard runs each tool instruction in path sequentially → tool_results[]
    ↓
[LLM] DA Agent interprets tool_results → session_state.da_findings
    ↓
DA findings appended to session_state.analysis_results
    ↓
[USER] Select new path (loop, max 3) OR proceed to DASHBOARD
    ↓
[LLM] BI Agent receives all analysis_results → KPI + chart config JSON
    ↓
[HARDCODED] Python renders Plotly charts from config → DASHBOARD stage
```

---

## Key Files

| File | Role |
|------|------|
| `app.py` | Streamlit UI + stage router + session state |
| `profiler.py` | Hardcoded pandas profiler |
| `starter_kit.py` | 10 hardcoded pandas analysis functions + TOOL_MAP |
| `switchboard.py` | Validates + executes tool instructions from Researcher |
| `pm_agent.py` | PM Agent — gates, transitions, context passing |
| `de_agent.py` | DE Agent — quality audit |
| `researcher_agent.py` | Researcher Agent — research path generation |
| `da_agent.py` | DA Agent — result interpretation |
| `bi_agent.py` | BI Agent — dashboard KPI + chart config (Stage 11) |
| `session_state_registry.md` | Full session_state key reference |

---

## Architecture Decisions

| Decision | Choice |
|----------|--------|
| Data processing | Pandas only — LLM never sees raw CSV |
| LLM output format | Strict JSON — Pydantic validates every response |
| Orchestration model | Parametric — Python controls flow, LLM triggers named functions |
| Agent memory | Stateless — full context passed explicitly on every call |
| State persistence | Streamlit session_state |
| Research path execution | Tools run sequentially per path. Results accumulate in list → passed together to DA Agent |
| Multi-path cap | Max 3 research paths per session |
| Dashboard trigger | User explicitly clicks "GO TO DASHBOARD" after ≥1 completed path |
| BI Agent input | Receives full `analysis_results[]` — all paths, not per-path |
| Chart rendering | BI Agent returns Plotly JSON config → `go.Figure(config)` — no LLM code execution |

---

## Session State Keys (summary)

| Key | Set by | Contains |
|-----|--------|----------|
| `stage` | app.py | Current pipeline stage string |
| `raw_data` | app.py | Uploaded DataFrame |
| `metadata` | profiler.py | Full profiler output dict |
| `de_findings` | de_agent.py | Quality score, issues, outliers |
| `pm_summary` | pm_agent.py | Latest PM user-facing message |
| `pm_summaries` | app.py | All PM messages across session (list) |
| `pm_ready` | pm_agent.py | Bool gate for stage transition |
| `research_paths` | researcher_agent.py | 5 generated paths |
| `current_path` | app.py | User-selected path dict |
| `tool_result` | switchboard.py | Latest tool output dict |
| `da_findings` | da_agent.py | Interpretation of tool results |
| `analysis_results` | app.py | Accumulated list of all completed path findings |
| `chart_configs` | bi_agent.py | Plotly chart config list (Stage 11) |
| `master_report` | app.py | Living markdown report string |
| `report_view` | app.py | Active tab in living report panel |
| `history_logs` | app.py | Timestamped terminal log entries |

> Full schema for each key: see `session_state_registry.md`

---

## Starter Kit Tools

10 hardcoded pandas functions in `starter_kit.py`. Each takes `df` + params, returns a result dict with a `"tool"` key. Registered in `TOOL_MAP` for parametric dispatch via Switchboard.

| Tool | Params |
|------|--------|
| `correlation_matrix` | `columns` (list, optional) |
| `time_series_trend` | `date_col`, `value_col` |
| `segment_comparison` | `group_col`, `value_col` |
| `distribution_analysis` | `col` |
| `top_n_values` | `col`, `n` (default 10) |
| `cohort_retention` | `date_col`, `id_col` |
| `funnel_analysis` | `stage_cols` (list) |
| `anomaly_detection` | `col` |
| `cross_tab` | `col1`, `col2` |
| `rolling_average` | `date_col`, `value_col`, `window` (default 7) |

---

## Build Plan

### ✅ Complete (Stages 1–10)

| Stage | What was built |
|-------|---------------|
| 1 | Environment, uv, repo structure |
| 2 | Session state, stage router, add_log() |
| 3 | Cyberpunk UI shell — 3-column layout, terminal, living report |
| 4 | Pandas profiler → metadata dict |
| 5 | Starter Kit — 10 analysis functions + TOOL_MAP |
| 6 | Tool Switchboard — Pydantic validation + parametric dispatch |
| 7 | PM Agent — gates, transitions, context passing |
| 8 | DE Agent — quality audit wired to app.py |
| 9 | Researcher Agent — 5 paths generated + user selection + multi-path loop |
| 10 | DA Agent — tool results interpreted + findings wired to app.py + multi-path UI |

---

### ⏳ Remaining

---

#### Stage 11 — BI Developer Agent + Dashboard
**What to build:** `bi_agent.py` — receives full `analysis_results[]` → returns list of Plotly chart configs + KPI summary as JSON. `app.py` DASHBOARD block wired: renders charts via `go.Figure()` + `st.plotly_chart()`.

**Key decisions:**
- BI Agent sees all completed paths holistically — not called per-path
- Returns fixed structure: 2–3 chart configs + a KPI summary block
- Pydantic validates chart type, data arrays, layout title
- Python renders — LLM never writes Plotly code

**Done when:** User completes ≥1 path → clicks GO TO DASHBOARD → sees 2–3 rendered Plotly charts.

---

#### Stage 12 — Synthesis Engine (Living Report)
**What to build:** Synthesis LLM call that rewrites `master_report` after each completed path. Receives all `analysis_results` → outputs coherent markdown narrative. Triggered automatically after DA Agent returns.

**Key decisions:**
- Replaces the full `master_report` on each call — not appended
- Input: all previous path headlines + insights + caveats
- Output: structured markdown with exec summary + per-path findings

**Done when:** Completing a path auto-updates the REPORT tab with a coherent cross-path narrative.

---

#### Stage 13 — Validation & Error Handling
**What to build:** Exponential backoff wrapper for all API calls, Pydantic coverage audit across all agents, graceful error display in UI (no raw tracebacks shown to user).

**Done when:** Simulated API failure shows a clean error message, not a crash.

---

#### Stage 14 — Deployment
**What to build:** Streamlit Cloud deploy, secrets management (no .env in cloud), README for portfolio.

**Done when:** Public URL works end-to-end with a real CSV.

---

## Key Design Principles

- **Pandas does the counting, AI does the thinking** — LLM never sees raw CSV
- **Prompts ARE the intelligence** — the app is just plumbing
- **PM Agent is the most critical** — holds context across all stateless agent calls
- **Parametric over agentic** — Python controls flow, LLM triggers named functions
- **Own every number** — if pandas produced it, you can verify it; if LLM produced it, validate with Pydantic
- **Slow is smooth, smooth is fast** — understand each stage before building the next
