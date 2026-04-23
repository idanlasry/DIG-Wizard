import pandas as pd
import numpy as np


def get_dataset_profile(df: pd.DataFrame) -> dict:
    """
    Hardcoded pandas profiler.
    Extracts structural metadata and statistical facts — no LLM involved.
    Returns a single profile dict that gets stored in session_state.metadata.
    """
    rows, cols = df.shape

    # ── 1. COLUMN METADATA ─────────────────────────────────────────────
    column_info = []
    for col in df.columns:
        null_count = int(df[col].isnull().sum())
        column_info.append(
            {
                "name": col,
                "dtype": str(df[col].dtype),
                "null_count": null_count,
                "null_pct": round((null_count / rows) * 100, 2),
                # Cast to str to avoid numpy type serialization issues downstream
                "sample_values": [str(v) for v in df[col].dropna().unique()[:5]],
            }
        )

    # ── 2. NUMERIC SUMMARY ─────────────────────────────────────────────
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    numeric_summary = {}

    for col in numeric_cols:
        series = df[col].dropna()

        # IQR outliers
        Q1 = series.quantile(0.25)
        Q3 = series.quantile(0.75)
        IQR = Q3 - Q1
        iqr_outliers = series[(series < (Q1 - 1.5 * IQR)) | (series > (Q3 + 1.5 * IQR))]

        # Z-score outliers (|z| > 3)
        mean = series.mean()
        std = series.std()
        if std > 0:
            z_scores = (series - mean) / std
            zscore_outliers = series[z_scores.abs() > 3]
        else:
            zscore_outliers = pd.Series([], dtype=series.dtype)

        numeric_summary[col] = {
            "mean": round(float(mean), 2),
            "std": round(float(std), 2),
            "min": round(float(series.min()), 2),
            "max": round(float(series.max()), 2),
            "outliers_iqr_count": int(len(iqr_outliers)),
            "outliers_zscore_count": int(len(zscore_outliers)),
            # Pass a few actual outlier values so the DE Agent can reason about them
            "outlier_sample_values": [
                round(float(v), 2) for v in iqr_outliers.head(5).tolist()
            ],
        }

    # ── 3. CATEGORICAL SUMMARY ─────────────────────────────────────────
    cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
    categorical_summary = {}

    for col in cat_cols:
        top_values = df[col].value_counts().head(5)
        categorical_summary[col] = {
            "unique_count": int(df[col].nunique()),
            # Convert keys to str — some categories are ints stored as object dtype
            "top_values": {str(k): int(v) for k, v in top_values.items()},
        }

    # ── 4. ASSEMBLE FINAL PROFILE ──────────────────────────────────────
    profile = {
        "shape": {"rows": rows, "cols": cols},
        "is_sample": is_sample,
        "full_row_count": rows,
        "duplicate_rows": int(df.duplicated().sum()),
        "columns": column_info,
        "numeric_summary": numeric_summary,
        "categorical_summary": categorical_summary,
    }

    return profile
