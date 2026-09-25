from __future__ import annotations

import os
from typing import Optional

import pandas as pd


def merge_csvs(
    csv_paths: list[str],
    output_csv_path: str,
    *,
    max_final_size: Optional[int] = None,
    seed: int = 42,
    logger=None,
) -> str:
    """Merge several CSVs with equal representation and save to *output_csv_path*.

    Mirrors `Funsearch/MultiRoundEvalTrainer/helpers.py::merge_csvs`.
    """
    frames: list[pd.DataFrame] = []
    for p in csv_paths:
        if not os.path.isfile(p):
            raise FileNotFoundError(f"CSV not found: {p}")
        df = pd.read_csv(p)
        frames.append(df)
        if logger:
            logger.info(f"  loaded {len(df)} rows from {p}")

    min_rows = min(len(df) for df in frames)
    for i, df in enumerate(frames):
        if len(df) > min_rows:
            if logger:
                logger.debug(
                    f"  Subsampling source {i} ({len(df)} → {min_rows} rows) for equal representation"
                )
            frames[i] = df.sample(n=min_rows, replace=False, random_state=seed)

    for col in ("story_index", "story_id"):
        offset = 0
        for df in frames:
            if col in df.columns:
                col_min = int(df[col].min())
                df[col] = df[col] - col_min + offset
                offset = int(df[col].max()) + 1

    merged = pd.concat(frames, ignore_index=True)

    if max_final_size is not None and len(merged) > max_final_size:
        if logger:
            logger.info(f"  Subsampling merged CSV: {len(merged)} → {max_final_size} rows")
        merged = merged.sample(n=max_final_size, replace=False, random_state=seed)

    os.makedirs(os.path.dirname(os.path.abspath(output_csv_path)), exist_ok=True)
    merged.to_csv(output_csv_path, index=False)
    if logger:
        logger.info(f"Merged CSV: {len(merged)} rows → {output_csv_path}")
    return output_csv_path

