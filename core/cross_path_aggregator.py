from collections import Counter


def build_cross_path_summary(analysis_results: list[dict], metadata: dict) -> dict:
    """
    Pure Python cross-path signal extractor. No LLM calls.
    Returns {} when analysis_results is empty (no prior paths completed yet).
    """
    if not analysis_results:
        return {}

    known_columns: set[str] = {
        col["name"] for col in metadata.get("columns", [])
    }

    # ── 1. COLUMN CITATION FREQUENCY ─────────────────────────────────────
    column_refs: Counter = Counter()
    for result in analysis_results:
        for instruction in result.get("path", {}).get("tool_instructions", []):
            for val in instruction.get("params", {}).values():
                if isinstance(val, str) and val in known_columns:
                    column_refs[val] += 1
                elif isinstance(val, list):
                    for v in val:
                        if isinstance(v, str) and v in known_columns:
                            column_refs[v] += 1

    # ── 2. STAT LABEL FREQUENCY (across da_findings) ──────────────────────
    label_to_occurrences: dict[str, list[dict]] = {}
    headlines: list[dict] = []
    all_insights: list[dict] = []

    for result in analysis_results:
        path_title = result.get("path", {}).get("title", "?")
        da = result.get("da_findings", {})

        headlines.append({"path": path_title, "headline": da.get("headline", "")})

        for insight in da.get("key_insights", []):
            all_insights.append({"path": path_title, "insight": insight})

        for stat in da.get("supporting_stats", []):
            label = stat.get("label", "")
            if label not in label_to_occurrences:
                label_to_occurrences[label] = []
            label_to_occurrences[label].append(
                {
                    "path": path_title,
                    "value": stat.get("value", ""),
                    "context": stat.get("context", ""),
                }
            )

    shared_stat_labels = [
        label for label, entries in label_to_occurrences.items() if len(entries) >= 2
    ]

    potential_overlaps = [
        {"label": label, "occurrences": entries}
        for label, entries in label_to_occurrences.items()
        if len(entries) >= 2
    ]

    return {
        "paths_completed": len(analysis_results),
        "most_cited_columns": dict(column_refs.most_common()),
        "shared_columns": [col for col, count in column_refs.most_common() if count >= 2],
        "shared_stat_labels": shared_stat_labels,
        "potential_overlaps": potential_overlaps,
        "headlines": headlines,
        "all_insights": all_insights,
    }
