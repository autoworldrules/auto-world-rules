"""
Rescore a ProgramsDatabase using a new EdgeTransformer model.

Between rounds the evaluator changes (new ET trained on latest data), so
the programs carried forward from the previous round must be rescored
before the next round of evolution begins.

Typical usage from FullFlowParallel_llm_client::

    from Funsearch.MultiRoundEvalTrainer.rescore_database import rescore_database

    programs_db = rescore_database(
        old_db=programs_db,
        new_et_model_path=et_model_path,
        num_stories=num_stories,
        base_seed=base_seed,
        min_entities=min_entities,
        max_entities=max_entities,
        num_cands=num_cands,
        logger=main_logger,
    )
"""

import os
import sys
import logging
from statistics import median
from typing import Optional

this_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from DeepMindCodeReference.implementation import programs_database
from DeepMindCodeReference.implementation import config as db_config
from DeepMindCodeReference.implementation import code_manipulation
from Funsearch.Evaluator.evaluator import EvaluatorET


def _pick_representative(cluster) -> code_manipulation.Function:
    """Return the shortest program in *cluster* (likely the cleanest)."""
    return min(cluster._programs, key=lambda p: len(str(p)))


def rescore_database(
    old_db: programs_database.ProgramsDatabase,
    new_et_model_path: str,
    num_stories: int = 3,
    base_seed: int = 42,
    min_entities: int = 6,
    max_entities: int = 9,
    num_cands: int = 22,
    device: str = "cuda",
    logger: Optional[logging.Logger] = None,
) -> programs_database.ProgramsDatabase:
    """Rescore one representative program per cluster with a new ET model.

    For every island in *old_db*, the shortest program from each cluster is
    evaluated using a freshly-loaded ``EvaluatorET`` pointed at
    *new_et_model_path*.  The rescored programs are inserted into a brand-new
    ``ProgramsDatabase`` that has the same topology (number of islands, config)
    as *old_db*.

    Args:
        old_db: Database from the previous round.
        new_et_model_path: Path to the ``.pth`` checkpoint of the newly
            trained EdgeTransformer.
        num_stories: Stories generated per evaluation.
        base_seed: Base random seed for story generation.
        min_entities / max_entities / num_cands: Story-generation params.
        device: ``'cuda'`` or ``'cpu'``.
        logger: Optional logger.

    Returns:
        A new ``ProgramsDatabase`` containing only the rescored
        representatives, ready to seed the next round of evolution.
    """
    log = logger or logging.getLogger(__name__)

    # ---- 1. Create a standalone EvaluatorET with the new model ----
    evaluator = EvaluatorET(
        database=old_db,       # stored but unused by analyse()
        template=None,
        function_to_evolve=None,
        function_to_run=None,
        inputs=None,
        num_stories=num_stories,
        model_path=new_et_model_path,
        device=device,
    )
    log.info(
        f"Rescore: loaded new ET from {new_et_model_path} "
        f"on device={evaluator._device}"
    )

    # ---- 2. Build a fresh DB with the same config ----
    new_db = programs_database.ProgramsDatabase(
        config=db_config.ProgramsDatabaseConfig(
            functions_per_prompt=old_db._config.functions_per_prompt,
            num_islands=len(old_db._islands),
        ),
        template=old_db._template,
        function_to_evolve=old_db._function_to_evolve,
    )

    # ---- 3. Iterate old DB: one representative per cluster ----
    total_rescored = 0
    total_failed = 0

    for island_id, island in enumerate(old_db._islands):
        for sig, cluster in island._clusters.items():
            representative = _pick_representative(cluster)
            fn_str = str(representative)

            try:
                metrics = evaluator.analyse(
                    priority_fn_str=fn_str,
                    num_stories=num_stories,
                    base_seed=base_seed,
                    min_entities=min_entities,
                    max_entities=max_entities,
                    num_cands=num_cands,
                )

                if (
                    not metrics
                    or "mean_min_logprobs" not in metrics
                    or not metrics["mean_min_logprobs"]
                ):
                    log.warning(
                        f"Rescore: island {island_id} sig {sig} returned "
                        f"empty metrics — skipping"
                    )
                    total_failed += 1
                    continue

                new_score = -1 * median(metrics["mean_min_logprobs"])
                new_db.register_program(
                    program=representative,
                    island_id=island_id,
                    scores_per_test={"across_Story_scores": new_score},
                )
                total_rescored += 1

            except Exception as exc:
                log.warning(
                    f"Rescore: island {island_id} sig {sig} failed — "
                    f"{type(exc).__name__}: {exc}"
                )
                total_failed += 1

    log.info(
        f"Rescore complete: {total_rescored} programs rescored, "
        f"{total_failed} failed, across {len(old_db._islands)} islands"
    )
    return new_db
