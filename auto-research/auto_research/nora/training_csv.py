from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from typing import Optional

import pandas as pd

from auto_research.priority_loading import load_priority_fn
from auto_research.nora.prio_story_generator import PrioStoryGeneratorNoRa1_1
from auto_research.nora.story_query_generator import StoryQueryGeneratorNoRa1_1


def _default_rules_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "NoRa1.1.txt"))


def _generate_single_story(args: tuple) -> pd.DataFrame:
    (
        story_idx,
        seed,
        priority_fn_path,
        min_entities,
        max_entities,
        num_cands,
        rules_path,
    ) = args

    priority_fn = load_priority_fn(priority_fn_path)
    gen = PrioStoryGeneratorNoRa1_1(
        priority_fn=priority_fn,
        seed=seed,
        min_entities=min_entities,
        max_entities=max_entities,
        num_cands=num_cands,
    )
    story_info = gen.generate_story_from_rules(rules_path)
    query_gen = StoryQueryGeneratorNoRa1_1()
    df_q = query_gen.build_query_dataframe(story_info)
    df_q["story_id"] = story_idx
    return df_q


def generate_training_csv(
    *,
    priority_fn_path: str,
    output_csv_path: str,
    num_stories: int = 100,
    base_seed: int = 42,
    min_entities: int = 5,
    max_entities: int = 8,
    num_cands: int = 32,
    rules_path: Optional[str] = None,
    max_workers: Optional[int] = None,
    logger=None,
) -> str:
    """Generate a training CSV from a priority function file.

    Seed scheme mirrors the historical helper: `seed = base_seed + 2*story_idx`.
    """
    if rules_path is None:
        rules_path = _default_rules_path()
    if max_workers is None:
        max_workers = min(num_stories, os.cpu_count() or 1)

    os.makedirs(os.path.dirname(os.path.abspath(output_csv_path)), exist_ok=True)

    work_items = [
        (
            idx,
            base_seed + 2 * idx,
            os.path.abspath(priority_fn_path),
            min_entities,
            max_entities,
            num_cands,
            rules_path,
        )
        for idx in range(num_stories)
    ]

    if logger:
        logger.info(
            f"Generating {num_stories} stories ({max_workers} workers) → {output_csv_path}"
        )

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        all_dfs = list(pool.map(_generate_single_story, work_items))

    final_df = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    final_df.to_csv(output_csv_path, index=False)

    if logger:
        logger.info(
            f"Saved {len(final_df)} query rows from {num_stories} stories to {output_csv_path}"
        )

    return output_csv_path

