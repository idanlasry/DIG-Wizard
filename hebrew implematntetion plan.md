Ready for review
Select text to add comments on the plan
Hebrew Language Support — DIG Wizard
Context
The company wants to support Hebrew-language dashboards. Only LLM outputs need to be in Hebrew — UI chrome (buttons, stage headers) stays in English. Hebrew text requires RTL rendering and UTF-8 encoding in the HTML report. The pipeline must run identically in both languages; the only forks are the language instruction injected into agent context, model selection for the two narrative agents (PM + Synthesis), and RTL CSS wrapping on the Streamlit side.

Language is selected by a toggle button at the top of the START stage. Additionally, if any column names contain Hebrew characters, the app auto-detects Hebrew and sets the language automatically.

Model Capability Assessment
Haiku is sufficient for structured JSON fields (labels, one-liners, category names). It handles Hebrew adequately for DE, Researcher, DA, and BI agents.

PM Agent and Synthesis Agent must switch to claude-sonnet-4-6 in Hebrew mode. These two produce free-form executive prose (multi-sentence narratives, recommendations). Hebrew morphology — verb conjugation, noun-adjective gender agreement, construct state — degrades noticeably at Haiku quality. Sonnet is already the intended model for PM post-MVP (the #! comment in pm_agent.py). Using Sonnet selectively for Hebrew prose keeps cost impact bounded to ~4 API calls per session.

Implementation Plan
1. utils/utils.py
Add pricing entry so calculate_cost doesn't fall back to the default when synthesis/PM calls Sonnet in Hebrew mode:

"claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
Add after the existing claude-sonnet-4-20250514 entry in MODEL_PRICING.

2. core/profiler.py
Add Hebrew auto-detection at the end of get_dataset_profile, just before return profile (line 98):

# ── 6. HEBREW COLUMN DETECTION ────────────────────────────────────
hebrew_range = range(0x0590, 0x0600)
profile["has_hebrew_columns"] = any(
    any(ord(ch) in hebrew_range for ch in col["name"])
    for col in column_info
)
This adds one boolean key to the metadata dict — no downstream Pydantic models are affected.

3. app.py — 6 focused changes
3a. Session state init (after line 175)
Inside the if "initialized" not in st.session_state: block, add:

st.session_state.language = "en"
3b. Language toggle in START stage (after line 531, ##### 📥 STEP 01: DATA INTAKE)
st.radio(
    "Language / שפה",
    options=["en", "he"],
    format_func=lambda x: "🇬🇧 English" if x == "en" else "🇮🇱 עברית",
    horizontal=True,
    key="language",
    label_visibility="collapsed",
)
Using key="language" binds directly to session_state.language — no callback needed.

3c. Auto-detect Hebrew after both upload paths
After st.session_state.metadata = profile in both the demo button block (line 540) and the file uploader block (line 585):

if profile.get("has_hebrew_columns"):
    st.session_state.language = "he"
3d. RTL CSS (inside the existing <style> block, before </style>)
.rtl-content {
    direction: rtl;
    text-align: right;
    font-family: 'Segoe UI', Arial, sans-serif;
}
The font override is important — the app's monospace terminal font has poor Hebrew glyph support.

3e. rtl_wrap() helper (add near the other builder functions, ~line 192)
def rtl_wrap(text: str) -> str:
    if st.session_state.get("language") == "he":
        return f"<div class='rtl-content'>{text}</div>"
    return text
Apply to LLM-generated text blocks using st.markdown(..., unsafe_allow_html=True):

RESEARCH stage: uip["rationale"], feasibility/limitations notes
ANALYSIS stage: da["headline"], each insight in key_insights, supporting stats label/context, caveats
DASHBOARD stage: dashboard_narrative, chart explanation, each recommendation in recommendations
LIVING REPORT column: the full content_md markdown block
3f. HTML report RTL + call site
In build_html_report() (line 192):

Add language: str = "en" parameter
Change <html> tag to: f'<html{" dir=\\"rtl\\"" if language == "he" else ""}>'
<meta charset="utf-8"> already exists at line 294 — no change needed
Update call site (~line 1231):

html_bytes = build_html_report(..., language=st.session_state.language)
3g. Pass language=st.session_state.language to all 8 agent call sites
Agent call	Approximate line
run_de_agent(profile)	~601
run_pm_gate(..., stage="AUDIT")	~629
run_researcher_agent(...)	~735
run_pm_gate(..., stage="RESEARCH")	~920
run_da_agent(...)	~1002
run_pm_gate(..., stage="DASHBOARD")	~1096
run_bi_agent(...)	~1118
run_synthesis_agent(...)	~1137
4. agents/de_agent.py
call_de_agent(metadata, language="en") — append to context if Hebrew:
if language == "he":
    context += "\n\nRESPOND IN HEBREW (עברית). All text fields must be in Hebrew."
run_de_agent(metadata, language="en") — forward to call_de_agent
Model stays Haiku.
5. agents/pm_agent.py
build_pm_context(..., language="en") — append language instruction to parts list
call_pm_agent(context, language="en"):
model = "claude-sonnet-4-6" if language == "he" else "claude-haiku-4-5-20251001"
Replace both hard-coded model strings with model variable.
run_pm_gate(..., language="en") — forward to both inner calls
6. agents/researcher_agent.py
build_researcher_context(..., language="en") — append instruction; specify which fields: title, question, rationale, feasibility_note, limitations_note
call_researcher_agent(..., language="en") — forward
run_researcher_agent(..., language="en") — forward
Model stays Haiku.
7. agents/da_agent.py
build_da_context(..., language="en") — append instruction; specify: headline, key_insights, label, context, viz_rationale, caveats
call_da_agent(..., language="en") — forward
run_da_agent(..., language="en") — forward
Model stays Haiku.
8. agents/bi_agent.py
build_bi_context(..., language="en") — append instruction; specify: label, context, title, x_label, y_label, explanation, dashboard_narrative
call_bi_agent(..., language="en") — forward
run_bi_agent(..., language="en") — forward
Model stays Haiku.
9. agents/synthesis_agent.py
build_synthesis_context(..., language="en") — append instruction; specify: narrative, recommendations
call_synthesis_agent(..., language="he"):
model = "claude-sonnet-4-6" if language == "he" else "claude-haiku-4-5-20251001"
Replace both hard-coded model strings. Also fix the pre-existing gap: add with_backoff import and wrap the API call (from utils.utils import with_backoff, calculate_cost).
run_synthesis_agent(..., language="en") — forward
Files Modified
File	Change summary
utils/utils.py	Add claude-sonnet-4-6 to MODEL_PRICING
core/profiler.py	Add has_hebrew_columns key to returned profile
app.py	session_state init, language radio, auto-detect, RTL CSS, rtl_wrap(), 8 call sites, HTML report
agents/de_agent.py	language param + context injection
agents/pm_agent.py	language param + context injection + Sonnet model switch
agents/researcher_agent.py	language param + context injection
agents/da_agent.py	language param + context injection
agents/bi_agent.py	language param + context injection
agents/synthesis_agent.py	language param + context injection + Sonnet model switch + with_backoff fix
9 files total. No Pydantic model field names change. No pipeline logic changes.

Verification
English regression: Load Bank Churn demo → run full pipeline → all outputs English, no RTL divs, HTML body has no dir.
Hebrew auto-detect: Upload CSV with a Hebrew column name (e.g., גיל) → confirm session_state.language == "he" before AUDIT.
Hebrew manual toggle: Load Bank Churn demo → flip radio to עברית → run pipeline → all 6 agent outputs are Hebrew prose.
RTL rendering: In Hebrew mode, ANALYSIS results render right-to-left in browser dev tools with class rtl-content.
Synthesis output: session_state.synthesis["narrative"] and ["recommendations"] are Hebrew text; JSON keys remain English.
HTML report: Download in Hebrew mode → open in browser → <html dir="rtl">, narrative/recommendations render RTL, <meta charset="UTF-8"> present.
Cost tracking: After PM call in Hebrew mode, estimated_cost_usd reflects Sonnet-tier pricing (not Haiku).
Pydantic keys: Raw JSON from any agent in Hebrew mode has English keys, Hebrew values only.