"""
post_round_processing.py
========================
End-of-round logic for the multi-round FunSearch loop.

After each round of FunSearch evolution cycles completes, this module:

1. Inspects the final database and logs summary statistics.
2. Extracts the best priority function from the database.
3. Generates an **eval.csv** from the best priority function (using a
   different seed than the training CSV) for model evaluation.
4. Generates a **base_train.csv** from the best priority function for
   training the next round's EdgeTransformer.
5. Trains a new EdgeTransformer on ``final_train.csv`` (merged from
   ``base_train.csv`` + previous round's ``final_train.csv`` +
   ``alt_training_sources_everyrnd``).
6. Evaluates the trained model on the current and previous round's eval
   CSVs, as well as on ``base_train.csv`` and ``final_train.csv``.
7. Records all metrics into a running ``records`` list (saved as
   ``records.pkl``).

records.pkl schema
------------------
``records.pkl`` contains a ``pd.DataFrame``, **one row per EdgeTransformer
model**.  The initial ET (``et_id = 0``) is trained before the first
evolution round from ``alt_training_sources_init``.  Subsequent ETs
(``et_id = N``) are trained at the end of round N from evolution-
generated data.

+---------------------------------+--------------------------------------------------+
| Column                          | Meaning                                          |
+=================================+==================================================+
| ``et_id``                       | 0 = initial ET (ET_0, trained before round 1     |
|                                 | from ``alt_training_sources_init``).             |
|                                 | N ≥ 1 = ET trained at end of round N.            |
+---------------------------------+--------------------------------------------------+
| ``model_path``                  | Absolute path to the ``.pth`` EdgeTransformer.   |
+---------------------------------+--------------------------------------------------+
| ``db_path``                     | Absolute path to the ProgramsDatabase pickle     |
|                                 | saved at the end of round N's evolution cycles.  |
|                                 | ``None`` for ``et_id = 0``.                      |
+---------------------------------+--------------------------------------------------+
| ``eval_csv``                    | Absolute path to ``eval.csv`` generated from the |
|                                 | best priority function of round N (uses          |
|                                 | ``base_seed + eval_seed_offset`` as seed).       |
|                                 | ``None`` for ``et_id = 0``.                      |
+---------------------------------+--------------------------------------------------+
| ``base_train_csv``              | Absolute path to ``base_train.csv`` generated    |
|                                 | from the best priority function of round N       |
|                                 | (uses ``base_seed`` as seed).                    |
|                                 | ``None`` for ``et_id = 0``.                      |
+---------------------------------+--------------------------------------------------+
| ``final_train_csv``             | Absolute path to ``final_train.csv``, the merged |
|                                 | training CSV used to train this ET.              |
|                                 | ET_0: merged ``alt_training_sources_init``.      |
|                                 | ET_N: ``base_train.csv`` + prev round's          |
|                                 | ``final_train.csv`` + ``alt_training_sources_    |
|                                 | everyrnd``.                                      |
+---------------------------------+--------------------------------------------------+
| ``et_val_acc``                  | Best validation accuracy (float) returned by     |
|                                 | Lightning during ET training.                    |
+---------------------------------+--------------------------------------------------+
| ``round_duration_s``            | Wall-clock seconds for the concluded round.      |
|                                 | ET_0: initial ET training time only.             |
|                                 | ET_N: full round N (evolution + post-processing).|
+---------------------------------+--------------------------------------------------+
| ``acc_round{N}_eval``           | Exact-match accuracy of this ET evaluated on     |
|                                 | round N's ``eval.csv``. Only for ``et_id ≥ 1``. |
+---------------------------------+--------------------------------------------------+
| ``acc_round{N-1}_eval``         | Exact-match accuracy of this ET evaluated on the |
|                                 | *previous* round's ``eval.csv``.                 |
|                                 | Only for ``et_id ≥ 2``.                          |
+---------------------------------+--------------------------------------------------+
| ``acc_round{N}_base_train``     | Exact-match accuracy of this ET evaluated on     |
|                                 | round N's ``base_train.csv``.                    |
|                                 | Only for ``et_id ≥ 1``.                          |
+---------------------------------+--------------------------------------------------+
| ``acc_round{N}_final_train``    | Exact-match accuracy of this ET evaluated on     |
|                                 | round N's ``final_train.csv``.                   |
|                                 | Only for ``et_id ≥ 1``.                          |
+---------------------------------+--------------------------------------------------+
| ``acc_round{N+1}_eval``         | Exact-match accuracy of this ET evaluated on the |
|                                 | *next* round's ``eval.csv``.  Back-filled when   |
|                                 | round N+1 completes post-processing.             |
|                                 | Only for ``et_id ≥ 1`` and when a subsequent     |
|                                 | round has been processed.                        |
+---------------------------------+--------------------------------------------------+

All ``acc_*`` values are mean exact-match accuracy (float in [0, 1])
averaged over stories in the respective CSV.

discoveries.pkl schema
----------------------
``discoveries.pkl`` contains a list of dicts (one per evolution cycle),
saved at ``<run_dir>/discoveries.pkl``.

An entry is appended **once per evolution cycle** by ``_run_funsearch_cycles``
in ``FullFlowParallel_llm_client.py``.  It counts how many programs in the
merged post-cycle database have a cluster score strictly exceeding the
**global best score that existed at the start of that cycle** (i.e. across
all islands, before any workers ran).  This is an aggregate count, not a
per-event log.

+----------------------------+----------------------------------------------+
| Column                     | Meaning                                      |
+============================+==============================================+
| ``round_num``              | Round number (1-indexed) in which this cycle  |
|                            | occurred.                                    |
+----------------------------+----------------------------------------------+
| ``cycle_number``           | Cycle number within the round (1-indexed).   |
+----------------------------+----------------------------------------------+
| ``num_new_discoveries``    | Number of individual programs whose cluster  |
|                            | score strictly exceeds the pre-cycle global   |
|                            | best.  Counts programs, not clusters.         |
+----------------------------+----------------------------------------------+

discovery_events.pkl schema
---------------------------
``discovery_events.pkl`` is a ``pd.DataFrame`` saved at
``<run_dir>/discovery_events.pkl``.  It is an **append-mode** file that
grows across rounds and cycles.

A row is appended whenever a sampler worker registers a program whose
score **strictly exceeds the current best score on its island's shard**
(``registered_score > best_score_per_island[island_id]``), as determined
inside ``EvaluatorWrapper.analyse()``.  Because each worker operates on
its own database shard, the comparison is against the shard-local island
best, not the global merged best.

Each worker accumulates events in memory via ``DiscoveryEventLogger``,
then flushes to a per-worker file
(``<round_dir>/sampler_logs/discovery_events_sampler{id}.pkl``) at the
end of sampling.  After all workers complete, ``consolidate_discovery_events()``
merges these per-worker files into the consolidated
``discovery_events.pkl`` and **deletes** the per-worker files.

+----------------------------+----------------------------------------------+
| Column                     | Meaning                                      |
+============================+==============================================+
| ``round_num``              | Round number (1-indexed).                    |
+----------------------------+----------------------------------------------+
| ``cycle_num``              | Cycle number within the round (1-indexed).   |
+----------------------------+----------------------------------------------+
| ``island_id``              | Island (shard-local) on which this program   |
|                            | became the new best.                         |
+----------------------------+----------------------------------------------+
| ``sampler_id``             | Worker / sampler process that discovered it.  |
+----------------------------+----------------------------------------------+
| ``registered_score``       | Score assigned to the program (``-1 *        |
|                            | median(mean_min_logprobs)``).  This score    |
|                            | was higher than the previous island best.    |
+----------------------------+----------------------------------------------+
| ``prio_fn_str``            | Full source code of the priority function    |
|                            | that was registered as the new island best.  |
+----------------------------+----------------------------------------------+
| ``formatted_prompt``       | The complete LLM prompt (after template      |
|                            | formatting) that was used to generate this   |
|                            | priority function.                           |
+----------------------------+----------------------------------------------+
"""

import logging
import os
import pickle
import sys
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from Funsearch.utils.inspect_database import inspect_database_shallow
from Funsearch.MultiRoundEvalTrainer.helpers import (
    extract_best_priority_fn_str,
    generate_training_csv,
    merge_csvs,
    train_edge_transformer,
    evaluate_model_on_csvs,
)


def run_post_round(
    round_num: int,
    round_dir: str,
    db_path: str,
    prev_round_dir: Optional[str],
    prev_final_train_csv: Optional[str],
    alt_training_sources_everyrnd: Optional[List[str]],
    records: List[Dict[str, Any]],
    round_start_time: float,
    # story generation params
    num_stories_train: int = 100,
    num_stories_eval: int = 100,
    base_seed: int = 42,
    eval_seed_offset: int = 10000,
    min_entities: int = 6,
    max_entities: int = 8,
    num_cands: int = 25,
    rules_path: Optional[str] = None,
    # training params
    epochs: int = 100,
    batch_size: int = 32,
    lr: float = 1e-3,
    training_seed: int = 42,
    dataset_type: str = "no_ambiguity_v2",
    max_final_training_size: Optional[int] = None,
    val_check_interval: int = 10,
    # evaluation params
    unique_labels_path: Optional[str] = None,
    eval_device: str = "cuda",
    eval_max_samples: Optional[int] = None,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """Execute all post-round processing and return a record for the ET
    trained at the end of this round.

    Each record in ``records`` describes **one EdgeTransformer model**.
    The ET trained here (``et_id = round_num``) will be used during
    the *next* round's evolution cycles.

    Parameters
    ----------
    round_num : int
        1-based round number.
    round_dir : str
        Directory for this round's outputs (already created).
    db_path : str
        Path to the saved ProgramsDatabase pickle for this round.
    prev_round_dir : str or None
        Directory of the previous round (None for round 1).
    prev_final_train_csv : str or None
        Path to the previous round's ``final_train.csv`` (None for round 1).
    alt_training_sources_everyrnd : list[str] or None
        Extra CSV paths merged into every round's ``final_train.csv``.
    records : list[dict]
        Running list of per-ET records (mutated in-place with new entry).
    round_start_time : float
        ``time.time()`` captured at the beginning of this round.
    num_stories_train, num_stories_eval : int
        Story counts for CSV generation.
    base_seed, eval_seed_offset : int
        Seeds for CSV generation.
    min_entities, max_entities, num_cands : int
        Story generation parameters.
    rules_path : str or None
        Path to rules file for story generation.
    epochs, batch_size, lr, training_seed : ...
        EdgeTransformer training hyper-parameters.
    dataset_type : str
        Dataset type for training.
    max_final_training_size : int or None
        Cap on final training CSV size.
    unique_labels_path : str or None
        Path to ``unique_labels.pkl``.
    eval_device : str
        Device for evaluation (``"cuda"`` or ``"cpu"``).
    eval_max_samples : int or None
        Max rows per CSV during evaluation.
    logger : logging.Logger or None

    Returns
    -------
    dict
        Record for the ET trained this round (also appended to *records*).
    """
    if logger is None:
        logger = logging.getLogger("PostRound")

    logger.info("=" * 80)
    logger.info(f"POST-ROUND PROCESSING — Round {round_num}")
    logger.info("=" * 80)

    # ------------------------------------------------------------------
    # 0. Final database inspection
    # ------------------------------------------------------------------
    logger.info("Database inspection:")
    inspect_database_shallow(db_path, logger=logger)

    # ------------------------------------------------------------------
    # 1. Extract best priority function
    # ------------------------------------------------------------------
    logger.info("Extracting best priority function from database …")
    best_priority_fn_str = extract_best_priority_fn_str(db_path, logger=logger)

    # Save it for reference
    prio_fn_path = os.path.join(round_dir, "best_priority_fn.py")
    with open(prio_fn_path, "w") as f:
        f.write(best_priority_fn_str)
    logger.info(f"Best priority function saved → {prio_fn_path}")

    # ------------------------------------------------------------------
    # 2. Generate eval.csv (different seed)
    # ------------------------------------------------------------------
    eval_csv_path = os.path.join(round_dir, "eval.csv")
    logger.info(f"Generating eval.csv ({num_stories_eval} stories, seed={base_seed + eval_seed_offset}) …")
    generate_training_csv(
        priority_fn_str=best_priority_fn_str,
        output_csv_path=eval_csv_path,
        num_stories=num_stories_eval,
        base_seed=base_seed + eval_seed_offset,
        min_entities=min_entities,
        max_entities=max_entities,
        num_cands=num_cands,
        rules_path=rules_path,
        logger=logger,
    )

    # ------------------------------------------------------------------
    # 2b. Backfill: evaluate the *previous* ET on this round's eval.csv
    # ------------------------------------------------------------------
    if records and records[-1].get("model_path"):
        prev_et_model = records[-1]["model_path"]
        prev_et_id = records[-1]["et_id"]
        logger.info(
            f"Backfill: evaluating ET_{prev_et_id} (previous) on "
            f"round {round_num}'s eval.csv …"
        )
        backfill_df = evaluate_model_on_csvs(
            model_path=prev_et_model,
            test_csv_paths=[eval_csv_path],
            unique_labels_path=unique_labels_path,
            device=eval_device,
            max_samples=eval_max_samples,
            logger=logger,
        )
        if not backfill_df.empty:
            backfill_acc = float(backfill_df.iloc[0]["mean_acc"])
            records[-1]["acc_roundN+1_eval"] = backfill_acc
            logger.info(
                f"Backfill: ET_{prev_et_id} acc on round {round_num} "
                f"eval.csv = {backfill_acc:.4f}"
            )

    # ------------------------------------------------------------------
    # 3. Generate base_train.csv (for next round's ET training)
    # ------------------------------------------------------------------
    base_train_csv_path = os.path.join(round_dir, "base_train.csv")
    # Minimum queries: if max_final_training_size is set, ensure we generate
    # at least max_final_training_size / 5 queries so the training CSV is not
    # too small.
    min_queries_train = None
    if max_final_training_size is not None:
        min_queries_train = max_final_training_size // 5
        logger.info(
            f"min_queries for base_train.csv set to "
            f"{min_queries_train} (et_max_final_training_size / 5)"
        )
    logger.info(f"Generating base_train.csv ({num_stories_train} stories, seed={base_seed}) …")
    generate_training_csv(
        priority_fn_str=best_priority_fn_str,
        output_csv_path=base_train_csv_path,
        num_stories=num_stories_train,
        base_seed=base_seed,
        min_entities=min_entities,
        max_entities=max_entities,
        num_cands=num_cands,
        rules_path=rules_path,
        logger=logger,
        min_queries=min_queries_train,
    )

    # ------------------------------------------------------------------
    # 4. Merge into final_train.csv and train ET for the next round
    # ------------------------------------------------------------------
    csvs_to_merge = [base_train_csv_path]
    if prev_final_train_csv and os.path.isfile(prev_final_train_csv):
        csvs_to_merge.append(prev_final_train_csv)
    if alt_training_sources_everyrnd:
        for src in alt_training_sources_everyrnd:
            if os.path.isfile(src):
                csvs_to_merge.append(src)

    final_train_csv_path = os.path.join(round_dir, "final_train.csv")
    logger.info("Merging CSVs into final_train.csv …")
    merge_csvs(
        csvs_to_merge,
        final_train_csv_path,
        max_final_size=max_final_training_size,
        seed=training_seed,
        logger=logger,
    )

    model_path = os.path.join(round_dir, "model.pth")
    import torch as _torch
    _cuda_ok = _torch.cuda.is_available()
    _et_device_str = (
        f"cuda:{_torch.cuda.current_device()} "
        f"({_torch.cuda.get_device_name(_torch.cuda.current_device())})"
        if _cuda_ok else "cpu (no CUDA available!)"
    )
    logger.info(f"ET round-{round_num} training device: {_et_device_str}  "
                f"(batch_size={batch_size}, epochs={epochs}, val_every={val_check_interval})")
    logger.info("Training EdgeTransformer …")
    model_path, et_val_acc = train_edge_transformer(
        train_csv_path=final_train_csv_path,
        model_output_path=model_path,
        unique_labels_path=unique_labels_path,
        dataset_type=dataset_type,
        epochs=epochs,
        batch_size=batch_size,
        lr=lr,
        seed=training_seed,
        log_dir=round_dir,
        val_check_interval=val_check_interval,
        logger=logger,
    )

    # ------------------------------------------------------------------
    # 5. Evaluate the trained model
    # ------------------------------------------------------------------
    logger.info("Evaluating trained model …")

    test_csvs: List[str] = []
    test_csv_labels: List[str] = []

    # Current round's eval.csv
    test_csvs.append(eval_csv_path)
    test_csv_labels.append("roundN_eval")

    # Previous round's eval.csv (if exists)
    if prev_round_dir:
        prev_eval = os.path.join(prev_round_dir, "eval.csv")
        if os.path.isfile(prev_eval):
            test_csvs.append(prev_eval)
            test_csv_labels.append("roundN-1_eval")

    # Current round's base_train.csv and final_train.csv
    test_csvs.append(base_train_csv_path)
    test_csv_labels.append("roundN_base_train")
    test_csvs.append(final_train_csv_path)
    test_csv_labels.append("roundN_final_train")

    summary_df = evaluate_model_on_csvs(
        model_path=model_path,
        test_csv_paths=test_csvs,
        unique_labels_path=unique_labels_path,
        device=eval_device,
        max_samples=eval_max_samples,
        logger=logger,
    )

    # Save evaluation summary CSV
    eval_summary_path = os.path.join(round_dir, "eval_summary.csv")
    summary_df.to_csv(eval_summary_path, index=False)
    logger.info(f"Evaluation summary saved → {eval_summary_path}")

    # ------------------------------------------------------------------
    # 6. Build record for this ET (exact-match accuracy only)
    # ------------------------------------------------------------------
    import time as _time  # for round_duration_s

    round_duration_s = _time.time() - round_start_time

    record: Dict[str, Any] = {
        "et_id": round_num,
        "model_path": model_path,
        "db_path": db_path,
        "eval_csv": eval_csv_path,
        "base_train_csv": base_train_csv_path,
        "final_train_csv": final_train_csv_path,
        "et_val_acc": et_val_acc,
        "round_duration_s": round_duration_s,
    }

    # Map summary rows to labelled accuracy entries
    for idx, row in summary_df.iterrows():
        csv_basename = row["test_csv"]
        label = test_csv_labels[idx] if idx < len(test_csv_labels) else csv_basename
        record[f"acc_{label}"] = row["mean_acc"]

    records.append(record)

    # ------------------------------------------------------------------
    # 7. Log the table so far
    # ------------------------------------------------------------------
    logger.info("\n" + "=" * 80)
    logger.info("PERFORMANCE TABLE (exact-match accuracy)")
    logger.info("=" * 80)
    records_df = pd.DataFrame(records)
    logger.info("\n" + records_df.to_string(index=False))

    logger.info(f"\nPost-round processing for round {round_num} completed!")
    return record


def train_initial_et(
    init_et_dir: str,
    alt_training_sources_init: List[str],
    alt_training_sources_everyrnd: Optional[List[str]],
    records: List[Dict[str, Any]],
    # training params
    epochs: int = 100,
    batch_size: int = 32,
    lr: float = 1e-3,
    training_seed: int = 42,
    dataset_type: str = "no_ambiguity_v2",
    max_final_training_size: Optional[int] = None,
    val_check_interval: int = 10,
    unique_labels_path: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> str:
    """Train the initial ET model (ET_0).

    Uses the **union** of ``alt_training_sources_init`` and
    ``alt_training_sources_everyrnd`` (deduplicated by absolute path)
    so that CSVs appearing in both lists are not included twice.

    Creates an ``et_id = 0`` record in *records* and returns the model path.
    The ET trained here is used during round 1's evolution cycles.

    Parameters
    ----------
    init_et_dir : str
        Directory for initial ET artefacts (e.g. ``run_dir/round_0/``).
    alt_training_sources_init : list[str]
        CSV files specific to the initial ET.
    alt_training_sources_everyrnd : list[str] or None
        CSV files used every round; also included in ET_0 (deduplicated).
    records : list[dict]
        Running list of per-ET records (mutated in-place with new entry).
    epochs, batch_size, lr, training_seed, dataset_type, max_final_training_size :
        Training hyper-parameters.
    unique_labels_path : str or None
    logger : logging.Logger or None

    Returns
    -------
    str
        Path to the trained model (``.pth``).
    """
    import time as _time

    if logger is None:
        logger = logging.getLogger("InitialET")

    logger.info("=" * 80)
    logger.info("TRAINING INITIAL ET MODEL (ET_0)")
    logger.info("=" * 80)

    start = _time.time()

    # Deduplicate: union of _init and _everyrnd by resolved absolute path
    seen: set[str] = set()
    all_sources: List[str] = []
    for src in alt_training_sources_init:
        resolved = os.path.abspath(src)
        if resolved not in seen:
            seen.add(resolved)
            all_sources.append(src)
    if alt_training_sources_everyrnd:
        for src in alt_training_sources_everyrnd:
            resolved = os.path.abspath(src)
            if resolved not in seen:
                seen.add(resolved)
                all_sources.append(src)

    valid_sources = [s for s in all_sources if os.path.isfile(s)]
    if not valid_sources:
        raise RuntimeError(
            "No valid CSV sources found for initial ET training. "
            f"Searched: {all_sources}"
        )

    os.makedirs(init_et_dir, exist_ok=True)

    final_train_csv = os.path.join(init_et_dir, "final_train.csv")
    merge_csvs(
        valid_sources,
        final_train_csv,
        max_final_size=max_final_training_size,
        seed=training_seed,
        logger=logger,
    )

    model_path = os.path.join(init_et_dir, "model.pth")
    import torch as _torch
    _cuda_ok = _torch.cuda.is_available()
    _et_device_str = (
        f"cuda:{_torch.cuda.current_device()} "
        f"({_torch.cuda.get_device_name(_torch.cuda.current_device())})"
        if _cuda_ok else "cpu (no CUDA available!)"
    )
    logger.info(f"ET_0 (initial) training device: {_et_device_str}  "
                f"(batch_size={batch_size}, epochs={epochs}, val_every={val_check_interval})")
    model_path, et_val_acc = train_edge_transformer(
        train_csv_path=final_train_csv,
        model_output_path=model_path,
        unique_labels_path=unique_labels_path,
        dataset_type=dataset_type,
        epochs=epochs,
        batch_size=batch_size,
        lr=lr,
        seed=training_seed,
        log_dir=init_et_dir,
        val_check_interval=val_check_interval,
        logger=logger,
    )

    duration = _time.time() - start

    # Record for the initial ET (et_id = 0)
    record: Dict[str, Any] = {
        "et_id": 0,
        "model_path": model_path,
        "db_path": None,
        "eval_csv": None,
        "base_train_csv": None,
        "final_train_csv": final_train_csv,
        "et_val_acc": et_val_acc,
        "round_duration_s": duration,
    }
    records.append(record)

    logger.info(f"Initial ET model saved → {model_path}  (val_acc={et_val_acc:.4f})")
    return model_path


def save_records(records: List[Dict[str, Any]], records_path: str,
                 logger: Optional[logging.Logger] = None) -> None:
    """Persist the records as a DataFrame pickle file."""
    df = pd.DataFrame(records)
    df.to_pickle(records_path)
    if logger:
        logger.info(f"Records saved → {records_path}")
