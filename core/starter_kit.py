import pandas as pd
import numpy as np
from scipy import stats


# ══════════════════════════════════════════════════════════════════════
# STARTER KIT LIBRARY
# 10 hardcoded pandas analysis functions.
# Each takes df + optional params, returns a structured result dict.
# No LLM involved. Triggered by name via the Tool Switchboard (Stage 6).
# ══════════════════════════════════════════════════════════════════════


def correlation_matrix(df: pd.DataFrame, columns: list = None) -> dict:
    """
    Computes pairwise Pearson correlations between numeric columns.
    Returns top 10 strongest pairs sorted by absolute correlation.
    """
    numeric_df = df.select_dtypes(include=[np.number])

    if columns:
        numeric_df = numeric_df[[c for c in columns if c in numeric_df.columns]]

    corr = numeric_df.corr()

    # Extract upper triangle only — avoids duplicate pairs
    pairs = []
    cols = corr.columns.tolist()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append(
                {
                    "col_a": cols[i],
                    "col_b": cols[j],
                    "correlation": round(float(corr.iloc[i, j]), 3),
                }
            )

    pairs_sorted = sorted(pairs, key=lambda x: abs(x["correlation"]), reverse=True)

    return {
        "tool": "correlation_matrix",
        "top_pairs": pairs_sorted[:10],
        "columns_used": cols,
    }


def time_series_trend(df: pd.DataFrame, date_col: str, value_col: str) -> dict:
    """
    Aggregates a value column by month over a date column.
    Returns monthly totals + overall trend direction.
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], infer_datetime_format=True)
    df = df.dropna(subset=[date_col, value_col])
    df["_period"] = df[date_col].dt.to_period("M")

    monthly = df.groupby("_period")[value_col].sum().reset_index()
    monthly["_period"] = monthly["_period"].astype(str)

    values = monthly[value_col].tolist()
    trend = (
        "up" if values[-1] > values[0] else "down" if values[-1] < values[0] else "flat"
    )

    return {
        "tool": "time_series_trend",
        "date_col": date_col,
        "value_col": value_col,
        "monthly_data": [
            {"period": row["_period"], "value": round(float(row[value_col]), 2)}
            for _, row in monthly.iterrows()
        ],
        "trend_direction": trend,
        "period_count": len(monthly),
    }


def segment_comparison(df: pd.DataFrame, group_col: str, value_col: str) -> dict:
    """
    Compares a numeric value across segments of a categorical column.
    Returns mean, count, and share per segment.
    """
    df = df.dropna(subset=[group_col, value_col])
    grouped = (
        df.groupby(group_col)[value_col].agg(["mean", "count", "std"]).reset_index()
    )
    grouped.columns = ["segment", "mean", "count", "std"]
    grouped = grouped.sort_values("mean", ascending=False)

    total = grouped["count"].sum()
    grouped["share_pct"] = (grouped["count"] / total * 100).round(2)

    return {
        "tool": "segment_comparison",
        "group_col": group_col,
        "value_col": value_col,
        "segments": [
            {
                "segment": str(row["segment"]),
                "mean": round(float(row["mean"]), 2),
                "count": int(row["count"]),
                "std": round(float(row["std"]), 2) if not np.isnan(row["std"]) else 0.0,
                "share_pct": float(row["share_pct"]),
            }
            for _, row in grouped.iterrows()
        ],
    }


def distribution_analysis(
    df: pd.DataFrame, col: str, filter_col: str = None, filter_val=None
) -> dict:
    """
    Analyzes the distribution of a numeric column.
    Optionally filters to a subset of rows before analysis.
    Returns histogram bins, skewness, kurtosis, and percentiles.

    filter_col: column to filter on (e.g. "Exited")
    filter_val: value to match (e.g. 1 or 0)
    """
    if filter_col is not None and filter_val is not None:
        df = df[df[filter_col] == filter_val]

    series = df[col].dropna()

    counts, bin_edges = np.histogram(series, bins=10)
    bins = [
        {
            "bin_start": round(float(bin_edges[i]), 2),
            "bin_end": round(float(bin_edges[i + 1]), 2),
            "count": int(counts[i]),
        }
        for i in range(len(counts))
    ]

    return {
        "tool": "distribution_analysis",
        "col": col,
        "filter": {"col": filter_col, "val": filter_val}
        if filter_col is not None
        else None,
        "row_count": len(series),
        "histogram_bins": bins,
        "skewness": round(float(series.skew()), 3),
        "kurtosis": round(float(series.kurt()), 3),
        "percentiles": {
            "p25": round(float(series.quantile(0.25)), 2),
            "p50": round(float(series.quantile(0.50)), 2),
            "p75": round(float(series.quantile(0.75)), 2),
            "p95": round(float(series.quantile(0.95)), 2),
        },
    }


def top_n_values(df: pd.DataFrame, col: str, n: int = 10) -> dict:
    """
    Returns the top N most frequent values in a column with counts and percentages.
    """
    total = len(df[col].dropna())
    counts = df[col].value_counts().head(n)

    return {
        "tool": "top_n_values",
        "col": col,
        "n": n,
        "values": [
            {
                "value": str(val),
                "count": int(count),
                "pct": round(count / total * 100, 2),
            }
            for val, count in counts.items()
        ],
    }


def cohort_retention(df: pd.DataFrame, date_col: str, id_col: str) -> dict:
    """
    Builds a monthly cohort retention matrix.
    Cohort = first month a user_id appears. Tracks how many return in subsequent months.
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], infer_datetime_format=True)
    df = df.dropna(subset=[date_col, id_col])
    df["_period"] = df[date_col].dt.to_period("M")

    # First month each ID appeared
    cohort_map = df.groupby(id_col)["_period"].min().rename("cohort")
    df = df.join(cohort_map, on=id_col)
    df["periods_since"] = (df["_period"] - df["cohort"]).apply(lambda x: x.n)

    matrix = (
        df.groupby(["cohort", "periods_since"])[id_col].nunique().unstack(fill_value=0)
    )

    # Convert to retention percentages relative to cohort size (period 0)
    retention = matrix.divide(matrix[0], axis=0).round(3) * 100

    return {
        "tool": "cohort_retention",
        "date_col": date_col,
        "id_col": id_col,
        "cohorts": [str(c) for c in retention.index.tolist()],
        "periods": retention.columns.tolist(),
        "retention_pct": {
            str(cohort): {
                int(period): round(float(val), 1) for period, val in row.items()
            }
            for cohort, row in retention.iterrows()
        },
    }


def funnel_analysis(df: pd.DataFrame, stage_cols: list) -> dict:
    """
    Computes conversion rates across an ordered list of boolean/binary stage columns.
    Each column should be 1/True if the user reached that stage.
    """
    results = []
    for i, col in enumerate(stage_cols):
        count = int(df[col].sum())
        prev_count = int(df[stage_cols[i - 1]].sum()) if i > 0 else count
        conversion = round(count / prev_count * 100, 2) if prev_count > 0 else 0.0

        results.append(
            {
                "stage": col,
                "count": count,
                "conversion_from_prev": conversion if i > 0 else 100.0,
            }
        )

    top_count = results[0]["count"] if results else 1
    for r in results:
        r["overall_conversion"] = round(r["count"] / top_count * 100, 2)

    return {"tool": "funnel_analysis", "stage_cols": stage_cols, "stages": results}


def anomaly_detection(df: pd.DataFrame, col: str) -> dict:
    """
    Flags anomalous values in a numeric column using both IQR and Z-score.
    Returns flagged rows with their values and reason.
    """
    series = df[col].dropna()

    # IQR bounds
    Q1 = series.quantile(0.25)
    Q3 = series.quantile(0.75)
    IQR = Q3 - Q1
    iqr_mask = (df[col] < (Q1 - 1.5 * IQR)) | (df[col] > (Q3 + 1.5 * IQR))

    # Z-score bounds
    mean = series.mean()
    std = series.std()
    if std > 0:
        z_mask = ((df[col] - mean) / std).abs() > 3
    else:
        z_mask = pd.Series([False] * len(df))

    combined_mask = iqr_mask | z_mask
    flagged = df[combined_mask][[col]].copy()
    flagged["reason"] = ""
    flagged.loc[iqr_mask & ~z_mask, "reason"] = "IQR"
    flagged.loc[z_mask & ~iqr_mask, "reason"] = "Z-score"
    flagged.loc[iqr_mask & z_mask, "reason"] = "IQR + Z-score"

    return {
        "tool": "anomaly_detection",
        "col": col,
        "total_flagged": int(combined_mask.sum()),
        "anomalies": [
            {
                "index": int(idx),
                "value": round(float(row[col]), 2),
                "reason": row["reason"],
            }
            for idx, row in flagged.head(20).iterrows()
        ],
    }


def cross_tab(df: pd.DataFrame, col1: str, col2: str) -> dict:
    """
    Builds a frequency cross-tabulation between two categorical columns.
    Returns counts and row-normalized percentages.
    """
    ct = pd.crosstab(df[col1], df[col2])
    ct_pct = pd.crosstab(df[col1], df[col2], normalize="index").round(3) * 100

    return {
        "tool": "cross_tab",
        "col1": col1,
        "col2": col2,
        "columns": [str(c) for c in ct.columns.tolist()],
        "rows": [
            {
                "row_label": str(idx),
                "counts": {str(c): int(ct.loc[idx, c]) for c in ct.columns},
                "pct": {
                    str(c): round(float(ct_pct.loc[idx, c]), 1) for c in ct_pct.columns
                },
            }
            for idx in ct.index
        ],
    }


def rolling_average(
    df: pd.DataFrame, date_col: str, value_col: str, window: int = 7
) -> dict:
    """
    Computes a rolling average of a value column over time.
    Returns raw daily values + smoothed rolling average.
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], infer_datetime_format=True)
    df = df.dropna(subset=[date_col, value_col])
    df = df.sort_values(date_col)

    daily = df.groupby(date_col)[value_col].sum().reset_index()
    daily["rolling_avg"] = daily[value_col].rolling(window=window, min_periods=1).mean()

    return {
        "tool": "rolling_average",
        "date_col": date_col,
        "value_col": value_col,
        "window": window,
        "data": [
            {
                "date": str(row[date_col].date()),
                "value": round(float(row[value_col]), 2),
                "rolling_avg": round(float(row["rolling_avg"]), 2),
            }
            for _, row in daily.iterrows()
        ],
    }


# ══════════════════════════════════════════════════════════════════════
# TOOL REGISTRY
# Maps string names → functions. Used by the Tool Switchboard (Stage 6)
# to execute the correct function from a JSON instruction.
# ══════════════════════════════════════════════════════════════════════

TOOL_MAP = {
    "correlation_matrix": correlation_matrix,
    "time_series_trend": time_series_trend,
    "segment_comparison": segment_comparison,
    "distribution_analysis": distribution_analysis,
    "top_n_values": top_n_values,
    "cohort_retention": cohort_retention,
    "funnel_analysis": funnel_analysis,
    "anomaly_detection": anomaly_detection,
    "cross_tab": cross_tab,
    "rolling_average": rolling_average,
}
